import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch
import collector

class CollectorTests(unittest.TestCase):
    def test_all_running_jobs_without_progress(self):
        def run(args, **kwargs):
            if args[0]=='squeue':return '123|custom-job|RUNNING|1:00|1:00:00|1|node|partition|None\n'
            return 'JobId=123 UserId=test(1) AllocTRES=cpu=1 WorkDir=/missing'
        with patch.object(collector,'run',side_effect=run), patch('sys.argv',['collector.py']), patch.dict(os.environ,{'SKYNET_GPU_TELEMETRY':'0','SKYNET_TRAINING_ONLY':'0'}),patch('protocol.discover',return_value=(None,[])):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):collector.main()
        data=json.loads(out.getvalue())
        self.assertEqual(data['jobs'][0]['name'],'custom-job')
        self.assertNotIn('batches',data)

    def test_allocation_not_request(self):
        self.assertEqual(collector.allocated_gpu('ReqTRES=gres/gpu:a40=1'),'Unknown')
        self.assertEqual(collector.allocated_gpu('AllocTRES=gres/gpu=2,gres/gpu:l40s=2'),'L40S × 2')
        self.assertEqual(collector.allocated_gpu('AllocTRES=cpu=2'),'CPU only')

    def test_reject_other_owner_logs(self):
        with patch('sys.argv',['collector.py','123']),patch.object(collector.getpass,'getuser',return_value='me'),patch.object(collector,'run',return_value='UserId=other(1)'):
            with self.assertRaises(ValueError):collector.main()

    def test_reject_command_injection(self):
        with patch('sys.argv',['collector.py','1;touch /tmp/no']),patch.object(collector,'run') as run:
            with self.assertRaises(ValueError):collector.main()
            run.assert_not_called()
