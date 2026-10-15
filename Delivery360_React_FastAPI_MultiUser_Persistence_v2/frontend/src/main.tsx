import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import {Plus,MessageSquare,Trash2,Send,Menu,Layers,Users,FileText,Activity,BookOpen,PenLine,LogOut,LockKeyhole} from 'lucide-react';
import './style.css';
type Workspace='assistant'|'resources'|'sows'|'health'|'knowledge';
type Conversation={id:string,title:string,workspace:Workspace,updated_at:string};
type Message={id?:string,role:'user'|'assistant',content:string};
type Identity={username:string,csrf_token:string};
const spaces:{id:Workspace,label:string,icon:React.ReactNode}[]=[{id:'assistant',label:'AI Assistant',icon:<MessageSquare size={17}/>},{id:'resources',label:'Resources',icon:<Users size={17}/>},{id:'sows',label:'SOW Management',icon:<FileText size={17}/>},{id:'health',label:'Delivery Health',icon:<Activity size={17}/>},{id:'knowledge',label:'Knowledge Hub',icon:<BookOpen size={17}/>}];
let csrfToken='';
async function api<T>(path:string,options?:RequestInit):Promise<T>{
 const method=(options?.method||'GET').toUpperCase();
 const headers:Record<string,string>={'Content-Type':'application/json'};
 if(!['GET','HEAD'].includes(method)&&csrfToken)headers['X-CSRF-Token']=csrfToken;
 const r=await fetch('/api'+path,{credentials:'same-origin',...options,headers:{...headers,...options?.headers}});
 if(!r.ok){let msg=`HTTP ${r.status}`;try{msg=(await r.json()).detail||msg}catch{}throw Error(msg)}
 return r.json();
}
function LoginPage({onLogin}:{onLogin:(identity:Identity)=>void}){
 const [username,setUsername]=useState('manager1'),[password,setPassword]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{
  const identity=await api<Identity>('/auth/login',{method:'POST',body:JSON.stringify({username,password})});
  csrfToken=identity.csrf_token;setPassword('');onLogin(identity);
 }catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <div className="login-screen"><form className="login-card" onSubmit={submit}>
  <div className="login-logo"><Layers size={27}/><strong>Delivery <span>360</span></strong></div>
  <h1>Sign in</h1><p>Access your personal delivery workspace and saved conversations.</p>
  <label htmlFor="username">Username</label><input id="username" value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" required/>
  <label htmlFor="password">Password</label><input id="password" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/>
  {error&&<div role="alert" className="error">{error}</div>}
  <button className="login-submit" disabled={busy}><LockKeyhole size={16}/>{busy?'Signing in...':'Sign in'}</button>
  <small>POC accounts: manager1 / manager2 · Synthetic demonstration data</small>
 </form></div>
}
function App(){
 const [identity,setIdentity]=useState<Identity|null>(null),[checking,setChecking]=useState(true);
 const [chats,setChats]=useState<Conversation[]>([]),[active,setActive]=useState<string|null>(null),[workspace,setWorkspace]=useState<Workspace>('assistant'),[messages,setMessages]=useState<Message[]>([]),[draft,setDraft]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[sidebar,setSidebar]=useState(true);
 const clear=()=>{csrfToken='';setIdentity(null);setChats([]);setActive(null);setMessages([]);setDraft('');setError('');setWorkspace('assistant')};
 useEffect(()=>{api<Identity>('/auth/me').then(i=>{csrfToken=i.csrf_token;setIdentity(i)}).catch(()=>{}).finally(()=>setChecking(false))},[]);
 const refresh=async()=>setChats(await api<Conversation[]>('/conversations'));
 useEffect(()=>{if(identity){refresh().catch(e=>setError(e.message))}},[identity?.username]);
 async function logout(){try{await api('/auth/logout',{method:'POST'})}catch{}clear()}
 async function open(c:Conversation){setError('');setActive(c.id);setWorkspace(c.workspace);try{const data=await api<{messages:Message[]}>('/conversations/'+c.id);setMessages(data.messages)}catch(e){setError((e as Error).message)}}
 async function fresh(w:Workspace=workspace){setError('');try{const c=await api<Conversation>('/conversations',{method:'POST',body:JSON.stringify({workspace:w})});await refresh();setActive(c.id);setWorkspace(w);setMessages([]);setSidebar(false)}catch(e){setError((e as Error).message)}}
 async function submit(e:React.FormEvent){e.preventDefault();if(!draft.trim()||busy)return;let id=active;const text=draft.trim();setDraft('');setBusy(true);setError('');try{if(!id){const c=await api<Conversation>('/conversations',{method:'POST',body:JSON.stringify({workspace})});id=c.id;setActive(id)}setMessages(prev=>[...prev,{role:'user',content:text}]);const response=await api<{answer:string}>('/conversations/'+id+'/messages',{method:'POST',body:JSON.stringify({content:text})});setMessages(prev=>[...prev,{role:'assistant',content:response.answer}]);await refresh()}catch(e){setError((e as Error).message);setMessages(prev=>prev.filter((m,i)=>!(i===prev.length-1&&m.role==='user'&&m.content===text)));setDraft(text)}finally{setBusy(false)}}
 async function remove(c:Conversation){if(!window.confirm('Delete this conversation?'))return;try{await api('/conversations/'+c.id,{method:'DELETE'});if(active===c.id){setActive(null);setMessages([])}await refresh()}catch(e){setError((e as Error).message)}}
 async function rename(c:Conversation){const title=window.prompt('Conversation title',c.title);if(!title?.trim())return;try{await api('/conversations/'+c.id,{method:'PATCH',body:JSON.stringify({title:title.trim()})});await refresh()}catch(e){setError((e as Error).message)}}
 if(checking)return <div className="login-screen">Loading Delivery 360...</div>;
 if(!identity)return <LoginPage onLogin={i=>{setIdentity(i);setWorkspace('assistant')}}/>;
 return <div className="shell"><aside className={'sidebar '+(!sidebar?'collapsed':'')}><div className="brand"><Layers size={22}/><strong>Delivery <span>360</span></strong></div><button className="new" onClick={()=>fresh()}><Plus size={18}/> New conversation</button><div className="nav-title">WORKSPACES</div><nav>{spaces.map(s=><button key={s.id} className={'nav-item '+(workspace===s.id?'selected':'')} onClick={()=>{setWorkspace(s.id);setActive(null);setMessages([]);setSidebar(false)}}>{s.icon}{s.label}</button>)}</nav><div className="nav-title">RECENT CONVERSATIONS</div><div className="chat-list">{chats.map(c=><div key={c.id} className={'chat-entry '+(active===c.id?'selected':'')}><button className="chat-name" onClick={()=>open(c)} title={c.title}><MessageSquare size={14}/><span>{c.title}</span></button><button title="Rename" onClick={()=>rename(c)}><PenLine size={13}/></button><button title="Delete" onClick={()=>remove(c)}><Trash2 size={13}/></button></div>)}</div><div className="user-footer"><span>Signed in: <strong>{identity.username}</strong></span><button title="Sign out" onClick={logout}><LogOut size={16}/> Sign out</button></div><div className="foot">Synthetic demonstration data · Not connected to production</div></aside><main><header><button className="icon-btn" title="Toggle sidebar" onClick={()=>setSidebar(x=>!x)}><Menu size={20}/></button><div className="heading">{spaces.find(x=>x.id===workspace)?.label}<small>Delivery 360 Intelligence</small></div><button className="header-new" onClick={()=>fresh()}><Plus size={17}/> New chat</button></header><section className="conversation">{messages.length===0?<div className="welcome"><div className="welcome-icon"><Layers size={30}/></div><h1>How can I help with delivery today?</h1><p>Ask about staffing, SOW coverage, resource availability, utilization, or delivery risks.</p><div className="suggestions">{['Which SOWs expire in the next 30 days?','Find Databricks engineers available in November','Show delivery risks for Harbor Insurance','Which onboarding tasks are blocked?'].map(x=><button key={x} onClick={()=>setDraft(x)}>{x}</button>)}</div></div>:<div className="messages">{messages.map((m,i)=><div key={m.id||i} className={'message '+m.role}><div className="avatar">{m.role==='assistant'?'D360':'You'}</div><div className="bubble">{m.role==='assistant'?<ReactMarkdown>{m.content}</ReactMarkdown>:m.content}</div></div>)}{busy&&<div className="thinking">Analyzing delivery data...</div>}</div>}</section><div className="composer-wrap">{error&&<div role="alert" className="error">{error}</div>}<form className="composer" onSubmit={submit}><textarea aria-label="Message" value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit(e)}}} placeholder="Ask Delivery 360..." rows={2}/><button disabled={busy||!draft.trim()} aria-label="Send"><Send size={19}/></button></form><p className="disclaimer">POC data is synthetic. Validate operational decisions against authoritative systems.</p></div></main></div>
}
createRoot(document.getElementById('root')!).render(<App/>);
