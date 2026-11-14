import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import backend as b

class SetupTests(unittest.TestCase):
    def test_fresh_setup_preserves_key_and_uses_loopback(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); binary=base/'binary';binary.touch()
            with patch.multiple(b,STATE=base/'state',CONFIG=base/'cfg/config.yaml',AUTH=base/'auth',BIN=binary,UNIT=base/'units/core.service'):
                with patch.object(b,'run'):
                    b.configure();port,key=b.settings();before=b.CONFIG.read_bytes();b.configure()
                    self.assertEqual(port,8317);self.assertTrue(key.startswith('sk-station-'))
                    self.assertEqual(b.CONFIG.read_bytes(),before)
                    if not b.WINDOWS:self.assertEqual(b.CONFIG.stat().st_mode&0o777,0o600)
                    self.assertIn('127.0.0.1',before.decode())
    def test_accounts_tolerate_bad_files(self):
        with tempfile.TemporaryDirectory() as d,patch.object(b,'AUTH',Path(d)):
            (b.AUTH/'good.json').write_text('{"type":"codex","email":"demo@example.com"}')
            (b.AUTH/'bad.json').write_text('{')
            self.assertEqual(b.accounts(),'demo@example.com')
