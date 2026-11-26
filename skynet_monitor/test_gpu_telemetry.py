import unittest
from unittest.mock import patch
from gpu_telemetry import attach

class TelemetryTests(unittest.TestCase):
    def test_process_isolation_and_array_identity(self):
        jobs=[dict(id='1',node='node',gpu='A40 × 1'),
              dict(id='2_3',gpu_job_id='8',node='node',gpu='A40 × 1'),
              dict(id='3',node='node',gpu='CPU only')]
        def sample(item):
            return item[0],dict(devices=[dict(job_id='8',used_mib=42)],sampled_at=123)
        with patch('gpu_telemetry.collect_job',side_effect=sample):attach(jobs)
        self.assertEqual(jobs[0]['gpu_live']['devices'],[])
        self.assertEqual(jobs[1]['gpu_live']['devices'][0]['used_mib'],42)
        self.assertEqual(jobs[2]['gpu_live']['error'],'CPU only')

    def test_failure_not_zero(self):
        jobs=[dict(id='1',node='node',gpu='A40 × 1')]
        with patch('gpu_telemetry.collect_job',return_value=('1',dict(error='Unavailable',devices=[]))):attach(jobs)
        self.assertEqual(jobs[0]['gpu_live']['error'],'Unavailable')
        self.assertEqual(jobs[0]['gpu_live']['devices'],[])
