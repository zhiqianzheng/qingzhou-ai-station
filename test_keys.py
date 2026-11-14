import json
from pathlib import Path
import tempfile
import unittest
import yaml
from key_manager import KeyManager, fingerprint
from recorder import Store

class KeyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.config=self.root/'config.yaml'
        self.config.write_text('server:\n  host: 127.0.0.1\n  port: 8317\naccess:\n  api-keys:\n    - existing-key\nrequests:\n  proxy-url: http://127.0.0.1:7897\n',encoding='utf-8')
        self.manager=KeyManager(self.config,self.root/'state')
    def tearDown(self):self.temp.cleanup()
    def active_keys(self):return yaml.safe_load(self.config.read_text(encoding='utf-8'))['access']['api-keys']
    def test_import_create_disable_enable_delete_and_keep_old_identity(self):
        old=self.manager.list()[0];self.assertEqual(old['secret'],'existing-key')
        new=self.manager.create('客户甲');self.assertNotEqual(new['id'],old['id'])
        self.assertEqual(len(self.active_keys()),2)
        self.manager.update(new['id'],enabled=False);self.assertNotIn(new['secret'],self.active_keys())
        self.manager.update(new['id'],enabled=True);self.assertIn(new['secret'],self.active_keys())
        self.manager.update(new['id'],name='客户乙')
        self.manager.update(new['id'],delete=True)
        self.assertEqual(self.active_keys(),['existing-key'])
        archived=next(e for e in self.manager.list(include_deleted=True) if e['id']==new['id'])
        self.assertEqual(archived['name'],'客户乙');self.assertTrue(archived['deleted']);self.assertIsNone(archived['secret'])
        config=yaml.safe_load(self.config.read_text(encoding='utf-8'))
        self.assertEqual(config['server']['port'],8317);self.assertEqual(config['requests']['proxy-url'],'http://127.0.0.1:7897')
    def test_cannot_disable_or_delete_last_enabled_key(self):
        old=self.manager.list()[0];before=self.config.read_bytes()
        for change in ({'enabled':False},{'delete':True}):
            with self.assertRaises(ValueError):self.manager.update(old['id'],**change)
            self.assertEqual(self.config.read_bytes(),before)
            self.assertTrue(self.manager.list()[0]['enabled'])
    def test_bad_name_does_not_add_key(self):
        with self.assertRaises(ValueError):self.manager.create('   ')
        self.assertEqual(self.active_keys(),['existing-key'])

class GroupedHistoryTests(unittest.TestCase):
    def test_fingerprints_and_separate_history(self):
        self.assertEqual(fingerprint('Bearer key-a'),fingerprint('key-a'))
        self.assertEqual(fingerprint('bearer key-a'),fingerprint('key-a'))
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);store.configure(enabled=True)
            a=store.begin('/v1/responses','Bearer key-a',{'input':'from A'})
            b=store.begin('/v1/responses','key-b',{'input':'from B'})
            store.finish(a,'reply A','200');store.finish(b,'reply B','200')
            self.assertEqual([r['id'] for r in store.recent(fingerprint('key-a'))],[a])
            self.assertEqual([r['id'] for r in store.recent(fingerprint('key-b'))],[b])
            self.assertEqual(store.detail(a)['response'],'reply A')
            self.assertEqual(store.detail(b)['response'],'reply B')
            self.assertEqual(store.recent('nonexistent'),[])
    def test_retention_is_per_key_and_filter_precedes_limit(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);s.configure(enabled=True)
            b=s.begin('/v1/responses','key-b',{'input':'B oldest'})
            aid=fingerprint('key-a')
            with s.connect() as c:
                c.executemany('INSERT INTO conversations(key_id,created,model,request,status) VALUES(?,1,?,?,?)',[(aid,'demo','[]','200')]*500)
            s.begin('/v1/responses','key-a',{'input':'A newest'})
            self.assertEqual(len(s.recent(aid)),500)
            self.assertEqual(s.recent(fingerprint('key-b'))[0]['id'],b)

class SharingTests(unittest.TestCase):
    def test_share_uses_public_url_and_blocks_disabled_or_local_only(self):
        from unittest.mock import patch
        import backend as b
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config=root/'config.yaml'
            config.write_text('access:\n  api-keys:\n    - demo-old-key\n')
            manager=KeyManager(config,root/'state');entry=manager.create('朋友 A')
            with patch.object(b,'key_manager',return_value=manager),patch.object(b,'active',return_value=True),patch.object(b,'public_status',return_value='# Funnel on:\nhttps://demo.ts.net (Funnel on)'):
                text=b.share_connection(entry['id'],'demo-model')
                self.assertIn(entry['secret'],text);self.assertIn('https://demo.ts.net/v1',text)
                self.assertIn('朋友 A',text);self.assertIn('demo-model',text);self.assertIn('使用告知',text)
                self.assertNotIn('127.0.0.1',text)
                with patch.object(b,'public_status',return_value='No serve config'):
                    with self.assertRaises(ValueError):b.share_connection(entry['id'],'demo-model')
                manager.update(entry['id'],enabled=False)
                with self.assertRaises(ValueError):b.share_connection(entry['id'],'demo-model')
