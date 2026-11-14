import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from capability_tester import Tester, Reply, ProbeFailure, Unverified, Transport, report_text

class FakeTransport:
    def __init__(self):self.calls=[]
    def request(self,base,path,payload=None,**kwargs):
        self.calls.append((base,path,payload))
        if path=='models':return Reply(200,{}, {'data':[{'id':'demo'}]})
        if kwargs.get('stream'):return Reply(200,{}, {'text':'STREAM_OK','complete':True})
        if path=='responses':return Reply(200,{}, {'output':[{'content':[{'text':'RESPONSE_OK'}]}]})
        if payload.get('tools'):return Reply(200,{}, {'choices':[{'message':{'tool_calls':[{'function':{'name':'station_probe','arguments':'{"value":"ping"}'}}]}}]})
        if payload.get('response_format'):text='{"ok":true}'
        elif isinstance(payload['messages'][0]['content'],list):text='blue,yellow'
        else:text='TEST_OK'
        return Reply(200,{}, {'choices':[{'message':{'content':text}}]})

class CapabilityTests(unittest.TestCase):
    def test_basic_checks_payloads_and_does_not_run_expensive_extensions(self):
        transport=FakeTransport()
        tester=Tester('key-secret','demo','http://localhost/v1',transport=transport)
        with patch.object(tester,'probe_websocket',return_value='WebSocket verified'):
            report=tester.run()
        by_id={r['id']:r for r in report['results']}
        for id in ('text','stream','responses','vision','functions','json','websocket'):self.assertEqual(by_id[id]['status'],'通过')
        for id in ('image','web','code','speech','transcription','embeddings'):self.assertEqual(by_id[id]['status'],'未测试')
        self.assertNotIn('key-secret',report_text(report))
        self.assertNotIn('images/generations',[c[1] for c in transport.calls])
    def test_timeout_rate_limit_and_unsupported_are_distinct(self):
        tester=Tester('secret','demo','http://localhost/v1',transport=FakeTransport())
        def fail(error):
            def fn():raise error
            return fn
        self.assertEqual(tester.execute('a','timeout',fail(TimeoutError()))['status'],'未验证')
        self.assertEqual(tester.execute('b','rate',fail(ProbeFailure(429)))['status'],'未验证')
        self.assertEqual(tester.execute('c','route',fail(ProbeFailure(404)))['status'],'不支持')
        self.assertEqual(tester.execute('d','arg',fail(ProbeFailure(400,unsupported=True)))['status'],'不支持')
        self.assertEqual(tester.execute('e','unknown400',fail(ProbeFailure(400)))['status'],'未验证')
    def test_generated_text_is_not_evidence_of_hosted_tool_execution(self):
        tester=Tester('secret','demo','http://localhost/v1',transport=FakeTransport())
        self.assertEqual(tester.execute('web','web',tester.probe_web)['status'],'未验证')
        self.assertEqual(tester.execute('code','code',tester.probe_code)['status'],'未验证')
    def test_cancel_does_not_send_requests(self):
        cancel=threading.Event();cancel.set();transport=FakeTransport()
        report=Tester('secret','demo','http://localhost/v1',cancel=cancel,transport=transport).run()
        self.assertEqual(transport.calls,[])
        self.assertTrue(all(row['status']=='已取消' for row in report['results']))

class RealTransportTests(unittest.TestCase):
    def setUp(self):
        self.seen=[];seen=self.seen
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                ok=self.headers.get('Authorization')=='Bearer selected-client-key'
                self.send_response(200 if ok else 401);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'data':[]} if ok else {'error':{'message':'wrong credential'}}).encode())
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(b'{"error":{"message":"selected-client-key unsupported feature"}}')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}/v1'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_uses_selected_key_and_stops_on_invalid_auth(self):
        transport=Transport('selected-client-key',threading.Event());transport.request(self.base,'models')
        self.assertEqual(self.seen,['Bearer selected-client-key'])
        report=Tester('another-key','demo',self.base).run()
        self.assertEqual(report['results'][0]['status'],'失败')
        self.assertEqual(len(self.seen),2)
        self.assertTrue(all(r['status']!='通过' for r in report['results']))
    def test_raw_provider_errors_are_not_in_report(self):
        transport=Transport('selected-client-key',threading.Event())
        tester=Tester('selected-client-key','demo',self.base,transport=transport)
        row=tester.execute('probe','test',lambda:transport.request(self.base,'chat/completions',{}))
        self.assertEqual(row['status'],'不支持')
        self.assertNotIn('selected-client-key',json.dumps(row))
