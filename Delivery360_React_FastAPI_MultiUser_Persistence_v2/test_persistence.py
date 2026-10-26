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

class AzureStartupTests(unittest.TestCase):
    def test_azure_without_sql_cannot_fall_back_to_sqlite(self):
        import asyncio, backend
        async def start():
            async with backend.lifespan(backend.app):
                self.fail('Azure startup must require SQL')
        with patch.dict(os.environ, {
            'WEBSITE_SITE_NAME':'deliver360',
            'DELIVERY360_AZURE_SQL_CONNECTION_STRING':'',
            'DELIVERY360_ALLOW_INSECURE_DEMO_AUTH':'true',
        }), patch.object(backend, 'create_database_from_csvs') as create_sqlite:
            with self.assertRaisesRegex(RuntimeError, 'requires DELIVERY360_AZURE_SQL_CONNECTION_STRING'):
                asyncio.run(start())
            create_sqlite.assert_not_called()

class DeferredDatasetTests(unittest.TestCase):
    def test_deferred_tables_are_not_queried_or_advertised(self):
        import delivery360_core as core
        with patch.dict(os.environ, {'DELIVERY360_DISABLED_TABLES':'leave_records,onboarding_steps,role_requirements,sow_named_resources'}):
            repo=core.AzureSQLRepository()
        self.assertIn('employees',repo.schema())
        self.assertNotIn('leave_records',repo.schema())
        with patch.object(core,'connect_azure_sql') as connect:
            with self.assertRaisesRegex(ValueError,'phase 2'):
                repo.read('leave_records')
            with self.assertRaisesRegex(ValueError,'phase 2'):
                repo.query_readonly('SELECT * FROM dbo.role_requirements',[])
            result=core.ToolExecutor(core.Delivery360Tools(repo)).execute('query_employee_database',{'sql':'SELECT * FROM dbo.leave_records','parameters':[]})
            self.assertFalse(result['ok'])
            self.assertIn('phase 2',result['error'])
            self.assertEqual(result['code'],'NOT_IN_CURRENT_PHASE')
            result=core.ToolExecutor(core.Delivery360Tools(repo)).execute('get_onboarding_status',{'employee_id':'any-employee','assignment_id':'any-assignment'})
            self.assertEqual(result['phase'],2)
            self.assertIn('not part of the current phase',result['error'])
            connect.assert_not_called()

class CurrentAccountTests(unittest.TestCase):
    def test_each_request_discovers_renamed_accounts_even_with_history(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        import delivery360_core as core
        with patch.dict(os.environ,{'DELIVERY360_DISABLED_TABLES':''}):
            repo=core.AzureSQLRepository()
        account={'account_id':'client-key','name':'Previous client name'}
        repo.read=Mock(side_effect=lambda entity:[dict(account)])
        executor=core.ToolExecutor(core.Delivery360Tools(repo))
        def call_response(call_id):
            payload={'type':'function_call','name':'get_employee_schema','arguments':'{}','call_id':call_id}
            call=SimpleNamespace(**payload,model_dump=lambda **kwargs:dict(payload))
            return SimpleNamespace(status='completed',output=[call])
        client=Mock()
        client.responses.create.side_effect=[call_response('first'),SimpleNamespace(status='completed',output=[],output_text='First answer'),
                                             call_response('second'),SimpleNamespace(status='completed',output=[],output_text='Second answer')]
        agent=core.Delivery360Agent(executor,client=client,trace=False)
        agent.ask('Show the account')
        account['name']='Renamed client'
        agent.ask('Show the account again')
        outputs=[json.loads(item['output']) for item in agent.history if item.get('type')=='function_call_output']
        self.assertEqual([out['data']['accounts'][0]['name'] for out in outputs],['Previous client name','Renamed client'])
        requests=client.responses.create.call_args_list
        for index in (0,2):
            self.assertEqual(requests[index].kwargs['tool_choice'],{'type':'function','name':'get_employee_schema'})
        for hardcoded in ('Northstar','Harbor','RGA Insurance','A100','A200',core.SNAPSHOT_DATE):
            self.assertNotIn(hardcoded,agent.system_prompt)

if __name__=='__main__': unittest.main()
