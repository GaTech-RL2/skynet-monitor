import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bind_run import bind
from collector import training_progress

class BindingTests(unittest.TestCase):
    def test_wrapper_name_and_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'HOME':tmp}):
            root=Path(tmp)/'campaign';(root/'configs').mkdir(parents=True)
            (root/'runs/actual').mkdir(parents=True)
            config=root/'configs/actual.json';config.write_text(json.dumps(dict(id='actual',steps=60000)))
            (root/'runs/actual/metrics.jsonl').write_text('{"step":40000}\n{"step":401')
            path=bind(config,'42')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with patch('collector.run',side_effect=AssertionError('Must use explicit binding')):
                result=training_progress(dict(id='42',name='wrapper-chain'))
            self.assertEqual((result['step'],result['target']),(40000,60000))
            self.assertIn('/runs/actual/',result['source'])
            binding=json.loads(path.read_text());binding['job_id']='43';path.write_text(json.dumps(binding))
            self.assertIn('identity mismatch',training_progress(dict(id='42',name='wrapper-chain'))['error'])

    def test_config_identity_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'HOME':tmp}):
            config=Path(tmp)/'configs/run.json';config.parent.mkdir()
            config.write_text('{"id":"run","steps":10}')
            bind(config,'42');config.write_text('{"id":"different","steps":10}')
            self.assertEqual(training_progress(dict(id='42',name='wrapper'))['error'],'Run identity mismatch')
