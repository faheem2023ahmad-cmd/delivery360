"""Run: python -m unittest -v test_persistence.py"""
import os, tempfile, unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

class FakeAgent:
    def __init__(self,executor,trace=False):
        self.executor=executor;self.history=[];self.turns=0;self.last_trace=[];self.client=None;self.model='mock'
    def ask(self,text,context_note=''):
        self.history.extend([{'role':'user','content':text},{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Answer '+text}]}])
        self.turns+=1
        return 'Answer '+text

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.environ['DELIVERY360_STATE_DIR']=self.tmp.name
        os.environ['OPENAI_API_KEY']='test-placeholder-not-real'
        import importlib, backend
        self.b=importlib.reload(backend)
        self.patcher=patch.object(self.b,'Delivery360Agent',FakeAgent)
        self.patcher.start()
        self.client=TestClient(self.b.app)
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.patcher.stop()
        self.tmp.cleanup()
    def login(self,username):
        r=self.client.post('/api/auth/login',json={'username':username,'password':'manager'})
        self.assertEqual(r.status_code,200)
        return {'X-CSRF-Token':r.json()['csrf_token']}
    def test_users_are_isolated_and_persist_after_restart(self):
        headers=self.login('manager1')
        r=self.client.post('/api/conversations',json={'workspace':'assistant'},headers=headers)
        cid=r.json()['id']
        for i in range(22):
            r=self.client.post('/api/conversations/'+cid+'/messages',json={'content':f'Question {i}'},headers=headers)
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(self.client.get('/api/conversations/'+cid).json()['messages']),44)
        self.client.post('/api/auth/logout',headers=headers)
        other=self.login('manager2')
        self.assertEqual(self.client.get('/api/conversations').json(),[])
        self.assertEqual(self.client.get('/api/conversations/'+cid).status_code,404)
        self.assertEqual(self.client.delete('/api/conversations/'+cid,headers=other).status_code,404)
        self.client.post('/api/auth/logout',headers=other)
        self.login('manager1')
        self.assertEqual(len(self.client.get('/api/conversations/'+cid).json()['messages']),44)
        with self.b.db_connect() as db:
            row=db.execute('SELECT turns,summary FROM conversations WHERE id=?',(cid,)).fetchone()
        self.assertEqual(row['turns'],22)
        self.assertTrue(row['summary'])
        self.assertLess(len(row['summary']),6500)
    def test_csrf_and_password(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'manager1','password':'wrong'}).status_code,401)
        self.login('manager1')
        self.assertEqual(self.client.post('/api/conversations',json={'workspace':'assistant'}).status_code,403)

if __name__=='__main__': unittest.main()
