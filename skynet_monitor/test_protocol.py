import datetime
import json
from pathlib import Path
import tempfile
import io
import collector
import unittest
from unittest.mock import patch
from protocol import discover, validate
from report_progress import report
from progress import estimate


class ProtocolTest(unittest.TestCase):
    def test_generic_processing_progress(self):
        standard = validate(self.data(job_id='42_0', kind='processing'), '42_0')
        queue='42_0|dataset-worker|RUNNING|1:00|4:00:00|1|node|normal|None'
        def command(args):
            return queue if args[0]=='squeue' else 'WorkDir=/tmp Command=/tmp/campaign/scripts/worker.sbatch'
        output=io.StringIO()
        with patch.dict('os.environ', {'SKYNET_TRAINING_ONLY':'1','SKYNET_GPU_TELEMETRY':'0'}), patch('sys.argv',['collector.py']), patch.object(collector,'run',side_effect=command), patch('protocol.discover',return_value=(standard,[])), patch('sys.stdout',output):
            collector.main()
        result=json.loads(output.getvalue())
        self.assertEqual(result['jobs'][0]['progress']['adapter'],'progress.json')
        self.assertNotIn('batches', result)

    def test_collector_discovers_unrecognized_running_job(self):
        standard = validate(self.data(job_id='42', kind='evaluation'), '42')
        queue = '42|new-unknown-name|RUNNING|1:00|1:00:00|1|node|normal|None\n43|other|PENDING|0:00|1:00:00|1||normal|Priority'
        def command(args):
            return queue if args[0] == 'squeue' else 'JobId=42 WorkDir=/tmp Command=/tmp/job.sh'
        output = io.StringIO()
        with patch.dict('os.environ', {'SKYNET_TRAINING_ONLY':'1','SKYNET_GPU_TELEMETRY':'0'}), patch('sys.argv', ['collector.py']), patch.object(collector, 'run', side_effect=command), patch('protocol.discover', return_value=(standard, [])), patch('sys.stdout', output):
            collector.main()
        result = json.loads(output.getvalue())
        self.assertEqual([j['id'] for j in result['jobs']], ['42'])
        self.assertEqual(result['jobs'][0]['progress']['adapter'], 'progress.json')

    def data(self, **extra):
        return dict(completed=20, total=100, unit='episodes', updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), **extra)

    def test_scoped_minimal_and_shared_identity(self):
        self.assertEqual(validate(self.data(), '42', scoped=True)['step'], 20)
        with self.assertRaises(ValueError):
            validate(self.data(), '42')
        with self.assertRaises(ValueError):
            validate(self.data(job_id='43'), '42')

    def test_invalid_values(self):
        for key, value in [('total', 0), ('completed', float('nan')), ('completed', -1),
                           ('completed', 101), ('completed', True), ('updated_at', '2026-01-01'), ('kind', 'invalid')]:
            data = self.data(job_id='42'); data[key] = value
            with self.assertRaises((ValueError, TypeError)):
                validate(data, '42')

    def test_writer_array_identity_and_discovery_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); registry = root/'registry'; work = root/'work'; work.mkdir()
            output = registry/'12_3/progress.json'
            with patch.dict('os.environ', {'SLURM_ARRAY_JOB_ID':'12','SLURM_ARRAY_TASK_ID':'3','SLURM_JOB_ID':'999'}):
                report(25,100,kind='evaluation',output=output)
            (work/'progress.json').write_text(json.dumps(self.data(job_id='999')))
            result, errors = discover(dict(id='12_3',name='arbitrary'), work, registry)
            self.assertEqual((result['step'],result['kind']), (25,'Evaluation'))
            self.assertEqual(errors, [])
            self.assertEqual(json.loads(output.read_text())['job_id'], '12_3')
            output.write_text('{partial')
            result, errors = discover(dict(id='12_3',name='arbitrary'), work, registry)
            self.assertIsNone(result); self.assertEqual(len(errors),1)

    def test_stage_change_resets_eta(self):
        history=[]
        def sample(step, timestamp, stage):
            p=dict(step=step,target=100,updated=timestamp,unit='items',stage=stage,adapter='progress.json')
            estimate(p,history,timestamp)
            return p
        sample(10,100,'a')
        self.assertIsNotNone(sample(20,160,'a')['eta_seconds'])
        self.assertIsNone(sample(25,200,'b')['eta_seconds'])
