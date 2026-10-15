"""Delivery 360: authenticated, user-isolated chat and bounded durable agent context."""
import hashlib, hmac, json, logging, os, secrets, sqlite3, threading, uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from delivery360_core import (generate_sample_csvs, create_database_from_csvs, SQLiteRepository,
    AzureSQLRepository, Delivery360Tools, ToolExecutor, Delivery360Agent, SNAPSHOT_DATE)
from azure_sql import azure_sql_enabled, connect as connect_azure_sql, ensure_business_schema, ensure_chat_schema
from context_service import bounded_history, summarize_archived, reference_updates, merge_references, context_note

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
STATE=Path(os.getenv('DELIVERY360_STATE_DIR', str(ROOT/'state')))
BUSINESS_DB=Path(os.getenv('DELIVERY360_DB_PATH', str(STATE/'delivery360_poc.db')))
CHAT_DB=Path(os.getenv('DELIVERY360_CHAT_DB_PATH', str(STATE/'delivery360_chats.db')))
LOCK=threading.RLock()
CONVERSATION_LOCKS={}
SESSION_DAYS=7
COOKIE='d360_session'
log=logging.getLogger('delivery360')


def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def db_connect():
    if azure_sql_enabled():
        with connect_azure_sql() as db:
            yield db
        return
    db=sqlite3.connect(str(CHAT_DB),timeout=30)
    try:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        with db:
            yield db
    finally:
        db.close()

def hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,260000)
    return salt.hex()+':'+digest.hex()

def check_password(password,stored):
    salt,expected=stored.split(':',1)
    actual=hash_password(password,bytes.fromhex(salt)).split(':',1)[1]
    return hmac.compare_digest(actual,expected)

def init_db():
    if azure_sql_enabled():
        if os.getenv('DELIVERY360_AZURE_SQL_INIT_SCHEMA','false').lower()=='true':
            with db_connect() as db:
                ensure_chat_schema(db)
        return
    CHAT_DB.parent.mkdir(parents=True,exist_ok=True)
    with db_connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, csrf_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL, FOREIGN KEY(username) REFERENCES users(username));
          CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
            workspace TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            agent_history TEXT NOT NULL DEFAULT '[]', turns INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '', refs_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(owner) REFERENCES users(username));
          CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
          CREATE TABLE IF NOT EXISTS tool_executions (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
            tool_name TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
          CREATE INDEX IF NOT EXISTS idx_owner_updated ON conversations(owner,updated_at);
          CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,created_at);
          CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username);
        ''')
        # Safe migration for an existing SQLite database created by the previous POC.
        cols={row['name'] for row in db.execute('PRAGMA table_info(conversations)')}
        for col,ddl in [('summary',"TEXT NOT NULL DEFAULT ''"),('refs_json',"TEXT NOT NULL DEFAULT '{}'")]:
            if col not in cols: db.execute(f'ALTER TABLE conversations ADD COLUMN {col} {ddl}')
        # Provision exactly the two requested demo users. Existing hashes are retained.
        for username in ('manager1','manager2'):
            if not db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
                password=os.getenv('DELIVERY360_'+username.upper()+'_PASSWORD','manager')
                db.execute('INSERT INTO users VALUES (?,?,?)',(username,hash_password(password),now()))

@asynccontextmanager
async def lifespan(app):
    if os.getenv('WEBSITE_SITE_NAME') and os.getenv('DELIVERY360_ALLOW_INSECURE_DEMO_AUTH','false').lower()!='true':
        raise RuntimeError('Demo credentials are disabled on Azure. Configure enterprise authentication before public deployment, or explicitly opt in to insecure POC mode.')
    if azure_sql_enabled():
        if os.getenv('DELIVERY360_AZURE_SQL_INIT_SCHEMA','false').lower()=='true':
            with db_connect() as db:
                ensure_business_schema(db)
        app.state.repo=AzureSQLRepository()
    else:
        DATA.mkdir(parents=True,exist_ok=True)
        BUSINESS_DB.parent.mkdir(parents=True,exist_ok=True)
        generate_sample_csvs(DATA)
        create_database_from_csvs(DATA,BUSINESS_DB)
        app.state.repo=SQLiteRepository(BUSINESS_DB)
    init_db()
    yield

app=FastAPI(title='Delivery 360 API',version='2.0.0',lifespan=lifespan)

class Login(BaseModel):
    username:str=Field(min_length=1,max_length=100)
    password:str=Field(min_length=1,max_length=200)

class NewConversation(BaseModel):
    workspace:str='assistant'
class RenameConversation(BaseModel):
    title:str=Field(min_length=1,max_length=120)
class SendMessage(BaseModel):
    content:str=Field(min_length=1,max_length=10000)

WORKSPACES={'assistant','resources','sows','health','knowledge'}

def sha(value): return hashlib.sha256(value.encode()).hexdigest()

def auth_session(request:Request):
    token=request.cookies.get(COOKIE,'')
    if not token: raise HTTPException(401,'Please sign in')
    with db_connect() as db:
        row=db.execute('SELECT username,csrf_hash,expires_at FROM sessions WHERE token_hash=?',(sha(token),)).fetchone()
    if not row or row['expires_at']<=now(): raise HTTPException(401,'Session expired; sign in again')
    # Double-submit style CSRF protection: secret sent in JSON at login and /me,
    # required in a custom header for all mutations.
    if request.method not in ('GET','HEAD','OPTIONS'):
        csrf=request.headers.get('X-CSRF-Token','')
        if not csrf or not hmac.compare_digest(sha(csrf),row['csrf_hash']):
            raise HTTPException(403,'Invalid CSRF token')
    return row['username']

@app.post('/api/auth/login')
def login(payload:Login,response:Response):
    with db_connect() as db:
        user=db.execute('SELECT password_hash FROM users WHERE username=?',(payload.username,)).fetchone()
        # Always perform PBKDF2 even for an unknown username.
        stored=user['password_hash'] if user else hash_password('not-the-password',b'\x00'*16)
        if not check_password(payload.password,stored) or not user:
            raise HTTPException(401,'Invalid username or password')
        token=secrets.token_urlsafe(40)
        csrf=sha('csrf:'+token)
        expires=(datetime.now(timezone.utc)+timedelta(days=SESSION_DAYS)).isoformat()
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(sha(token),payload.username,sha(csrf),expires))
    secure=os.getenv('DELIVERY360_COOKIE_SECURE','false').lower()=='true' or bool(os.getenv('WEBSITE_SITE_NAME'))
    response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='lax',max_age=SESSION_DAYS*86400,path='/')
    return {'username':payload.username,'csrf_token':csrf}

@app.get('/api/auth/me')
def me(request:Request,owner=Depends(auth_session)):
    # Stable per-session CSRF value supports several open browser tabs.
    return {'username':owner,'csrf_token':sha('csrf:'+request.cookies[COOKIE])}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,owner=Depends(auth_session)):
    with db_connect() as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?',(sha(request.cookies[COOKIE]),))
    response.delete_cookie(COOKIE,path='/')
    return {'ok':True}

@app.get('/api/health')
def health(): return {'status':'ok','snapshot':SNAPSHOT_DATE}

def get_conversation(cid,owner):
    with db_connect() as db:
        row=db.execute('SELECT * FROM conversations WHERE id=? AND owner=?',(cid,owner)).fetchone()
    if not row: raise HTTPException(404,'Conversation not found')
    return dict(row)

@app.get('/api/conversations')
def conversations(owner=Depends(auth_session)):
    with db_connect() as db:
        rows=db.execute('SELECT id,title,workspace,created_at,updated_at FROM conversations WHERE owner=? ORDER BY updated_at DESC',(owner,)).fetchall()
    return [dict(r) for r in rows]

@app.post('/api/conversations',status_code=201)
def create_conversation(payload:NewConversation,owner=Depends(auth_session)):
    if payload.workspace not in WORKSPACES: raise HTTPException(422,'Unknown workspace')
    cid=str(uuid.uuid4());ts=now()
    with db_connect() as db:
        db.execute('INSERT INTO conversations(id,owner,title,workspace,created_at,updated_at) VALUES (?,?,?,?,?,?)',(cid,owner,'New conversation',payload.workspace,ts,ts))
    return {'id':cid,'title':'New conversation','workspace':payload.workspace,'created_at':ts,'updated_at':ts}

@app.get('/api/conversations/{cid}')
def conversation(cid:str,owner=Depends(auth_session)):
    c=get_conversation(cid,owner)
    with db_connect() as db:
        rows=db.execute('SELECT id,role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,id',(cid,)).fetchall()
    return {'id':c['id'],'title':c['title'],'workspace':c['workspace'],'messages':[dict(r) for r in rows]}

@app.patch('/api/conversations/{cid}')
def rename(cid:str,payload:RenameConversation,owner=Depends(auth_session)):
    get_conversation(cid,owner)
    with db_connect() as db:
        db.execute('UPDATE conversations SET title=?,updated_at=? WHERE id=? AND owner=?',(payload.title.strip(),now(),cid,owner))
    return {'ok':True}

@app.delete('/api/conversations/{cid}')
def delete(cid:str,owner=Depends(auth_session)):
    get_conversation(cid,owner)
    with db_connect() as db:
        db.execute('DELETE FROM conversations WHERE id=? AND owner=?',(cid,owner))
    with LOCK: CONVERSATION_LOCKS.pop(cid,None)
    return {'ok':True}


def run_agent(cid,owner,content):
    with LOCK: lock=CONVERSATION_LOCKS.setdefault(cid,threading.Lock())
    with lock:
        row=get_conversation(cid,owner)
        if not os.getenv('OPENAI_API_KEY'): raise HTTPException(503,'OPENAI_API_KEY is not configured')
        service=Delivery360Tools(app.state.repo)
        executor=ToolExecutor(service)
        agent=Delivery360Agent(executor,trace=False)
        full_history=json.loads(row['agent_history'])
        recent,dropped=bounded_history(full_history)
        summary=row['summary']
        if dropped:
            summary=summarize_archived(summary,dropped,client=agent.client,model=agent.model)
        references=json.loads(row['refs_json'])
        agent.history=recent
        agent.turns=row['turns']
        try:
            answer=agent.ask(content,context_note=context_note(summary,references))
        except Exception as exc:
            log.exception('Agent failed for conversation %s',cid)
            raise HTTPException(502,f'Agent request failed ({type(exc).__name__}). Check server logs.') from exc
        # Keep only recent bounded model history; full visible messages are retained separately.
        new_history, newly_dropped=bounded_history(agent.history)
        if newly_dropped:
            summary=summarize_archived(summary,newly_dropped,client=agent.client,model=agent.model)
        references=merge_references(references,reference_updates(agent.last_trace))
        ts=now()
        title=content[:65] if row['title']=='New conversation' else row['title']
        user_id=str(uuid.uuid4());assistant_id=str(uuid.uuid4())
        with db_connect() as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(user_id,cid,'user',content,ts))
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(assistant_id,cid,'assistant',answer,ts))
            db.execute('UPDATE conversations SET agent_history=?,turns=?,title=?,updated_at=?,summary=?,refs_json=? WHERE id=? AND owner=?',
                (json.dumps(new_history,default=str),agent.turns,title,ts,summary,json.dumps(references),cid,owner))
            for event in agent.last_trace:
                db.execute('INSERT INTO tool_executions VALUES (?,?,?,?,?,?)',
                    (str(uuid.uuid4()),cid,assistant_id,event['tool'],'ok' if (event.get('result') or {}).get('ok') else 'error',ts))
        return {'answer':answer,'title':title,'updated_at':ts}

@app.post('/api/conversations/{cid}/messages')
async def send(cid:str,payload:SendMessage,owner=Depends(auth_session)):
    return await run_in_threadpool(run_agent,cid,owner,payload.content.strip())

DIST=ROOT/'frontend'/'dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
    @app.get('/{full_path:path}',include_in_schema=False)
    def spa(full_path:str):
        target=(DIST/full_path).resolve()
        if target.is_file() and target.is_relative_to(DIST.resolve()): return FileResponse(target)
        return FileResponse(DIST/'index.html')
