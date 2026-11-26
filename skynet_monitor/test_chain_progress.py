import json
import tempfile
from pathlib import Path
import unittest
from chain_progress import discover_config

class ChainProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='chain space ')
        self.root=Path(self.temp.name)
        (self.root/'configs').mkdir()
        self.config=self.root/'configs/actual.json'
        self.config.write_text(json.dumps(dict(id='actual',steps=60000)))
    def tearDown(self):self.temp.cleanup()
    def test_export_wrapper(self):
        script='export CAMPAIGN_ROOT="'+str(self.root)+'"\nexport RUN_ID=actual\nexec bash "$CAMPAIGN_ROOT/scripts/chain.sbatch"'
        self.assertEqual(discover_config(script,self.root),(self.config.resolve(),'actual'))
    def test_explicit_config_relative_and_variables(self):
        script='CONFIG=configs/actual.json\nexec python3 train.py --config "$CONFIG"'
        self.assertEqual(discover_config(script,self.root),(self.config.resolve(),'actual'))
    def test_no_execution_or_ambiguous(self):
        for script in ['export RUN_ID=actual',
                       'python3 train.py --config configs/actual.json\nRUN_ID=other',
                       'python3 train.py --config configs/actual.json --config configs/other.json',
                       'if true; then\nRUN_ID=actual\nfi',
                       'CONFIG=$(touch /tmp/must-not-execute)\npython3 train.py --config "$CONFIG"',
                       'source env.sh\npython3 train.py --config configs/actual.json',
                       'exec python3 train.py --config "$UNKNOWN"']:
            with self.subTest(script=script),self.assertRaises(ValueError):discover_config(script,self.root)
    def test_identity_mismatch(self):
        self.config.write_text('{"id":"other","steps":10}')
        script='export CAMPAIGN_ROOT="'+str(self.root)+'"\nexport RUN_ID=actual\nexec bash chain.sbatch'
        with self.assertRaises(ValueError):discover_config(script,self.root)
