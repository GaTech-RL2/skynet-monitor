import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallTests(unittest.TestCase):
    def test_isolated_install_preserves_key_and_port(self):
        with tempfile.TemporaryDirectory(prefix='monitor space ') as tmp:
            home=Path(tmp)
            a=installer.install(home,ROOT,24681,True)
            key=Path(a['key']).read_text()
            b=installer.install(home,ROOT,None,True,gpu=False)
            self.assertEqual(b['port'],24681)
            self.assertEqual(Path(b['key']).read_text(),key)
            self.assertEqual(Path(b['key']).stat().st_mode&0o777,0o600)
            unit=Path(b['unit']).read_text()
            self.assertIn('--no-gpu-telemetry',unit)
            self.assertIn('Restart=always',unit)
            self.assertIn('127.0.0.1', (home/'.local/share/skynet-monitor/server.py').read_text())
            self.assertFalse((home/'.local/share/skynet-monitor/test_protocol.py').exists())

    def test_unit_quote(self):
        self.assertEqual(installer.quote('/tmp/100% space'),'"/tmp/100%% space"')
