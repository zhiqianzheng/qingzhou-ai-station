import json
import tempfile
import unittest
from pathlib import Path
from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from recorder import Store, create_app, extract_response

class StoreTests(unittest.TestCase):
    def test_opt_in_clear_and_key_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);payload={'model':'demo','messages':[{'role':'user','content':'hello'}]}
            self.assertIsNone(s.begin('/v1/chat/completions','secret',payload))
            s.configure(enabled=True);row=s.begin('/v1/chat/completions','secret',payload)
            s.finish(row,'hello too','200')
            self.assertNotIn('secret',s.db.read_bytes().decode(errors='ignore'))
            self.assertEqual(s.detail(row)['response'],'hello too')
            s.clear();s.finish(row,'in flight','200');self.assertEqual(s.recent(),[])
    def test_responses_stream(self):
        data=b'data: {"type":"response.output_text.delta","delta":"Hello"}\n\ndata: {"type":"response.output_text.delta","delta":" world"}\n\n'
        self.assertEqual(extract_response(data,'text/event-stream'),'Hello world')

class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.store.configure(enabled=True)
        async def upstream(req):
            if req.headers.get('Authorization')!='Bearer correct':return web.Response(status=401)
            if req.headers.get('Upgrade','').lower()=='websocket':
                ws=web.WebSocketResponse();await ws.prepare(req)
                async for msg in ws:
                    if msg.type==WSMsgType.TEXT:
                        await ws.send_json({'type':'response.output_text.delta','delta':'ws answer'})
                        await ws.send_json({'type':'response.completed','response':{'output':[{'content':[{'text':'ws answer'}]}]}})
                return ws
            self.last_body=await req.json()
            if self.last_body.get('stream'):
                r=web.StreamResponse(headers={'Content-Type':'text/event-stream'});await r.prepare(req)
                for token in ('Hello',' world'):
                    await r.write(('data: '+json.dumps({'choices':[{'delta':{'content':token}}]})+'\n\n').encode())
                await r.write(b'data: [DONE]\n\n');return r
            return web.json_response({'choices':[{'message':{'content':'Hello world'}}]})
        upstream_app=web.Application();upstream_app.router.add_route('*','/{tail:.*}',upstream)
        self.upstream=TestServer(upstream_app);await self.upstream.start_server()
        self.client=TestClient(TestServer(create_app(self.store,str(self.upstream.make_url('')).rstrip('/'))));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();await self.upstream.close();self.temp.cleanup()
    async def send(self,stream=False,key='correct'):
        return await self.client.post('/v1/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':'demo','messages':[{'role':'user','content':'question'}],'stream':stream})
    async def test_normal_and_streaming_forwarding(self):
        for stream in (False,True):
            r=await self.send(stream);self.assertEqual(r.status,200);data=await r.read()
            self.assertEqual(r.headers['X-AI-Station-Recording'],'enabled')
            self.assertIn(b'Hello',data)
            rows=self.store.recent();row=self.store.detail(rows[0]['id'])
            self.assertEqual(row['response'],'Hello world');self.assertIn('question',row['request'])
            self.assertNotIn('correct',self.store.db.read_bytes().decode(errors='ignore'))
    async def test_invalid_key_and_disabled_do_not_record(self):
        r=await self.send(key='bad');await r.read();self.assertEqual(r.status,401);self.assertEqual(self.store.recent(),[])
        self.store.configure(enabled=False);r=await self.send();await r.read()
        self.assertEqual(self.store.recent(),[])
    async def test_websocket_round_trip(self):
        ws=await self.client.ws_connect('/v1/responses',headers={'Authorization':'Bearer correct'})
        await ws.send_json({'type':'response.create','response':{'model':'demo','input':'ws question'}})
        self.assertEqual((await ws.receive_json())['delta'],'ws answer')
        self.assertEqual((await ws.receive_json())['type'],'response.completed')
        await ws.close()
        rows=self.store.recent();self.assertEqual(len(rows),1)
        self.assertIn('ws question',self.store.detail(rows[0]['id'])['request'])
        self.assertEqual(self.store.detail(rows[0]['id'])['response'],'ws answer')
