"""Read-only GPU telemetry, attributed by process cgroup and GPU UUID."""
import concurrent.futures
import json
import re
import subprocess
from pathlib import Path

NODE_SCRIPT = r'''import csv,json,os,re,subprocess,time
from pathlib import Path
def query(fields,kind):
 return list(csv.reader(subprocess.check_output(['nvidia-smi','--query-'+kind+'='+fields,'--format=csv,noheader,nounits'],text=True,timeout=4).splitlines(),skipinitialspace=True))
def number(s):
 try:return float(s)
 except ValueError:return None
gpus={u:dict(uuid=u,index=i,utilization=number(v),total_mib=number(t)) for i,u,v,t in query('index,uuid,utilization.gpu,memory.total','gpu')}
rows={}
for pid,uuid,memory in query('pid,gpu_uuid,used_gpu_memory','compute-apps'):
 try:
  p=Path('/proc')/pid
  if p.stat().st_uid!=os.getuid():continue
  match=re.search(r'/job_(\d+)(?:/|$)',(p/'cgroup').read_text())
  if not match or uuid not in gpus:continue
  key=(match[1],uuid)
  row=rows.setdefault(key,dict(gpus[uuid],job_id=match[1],used_mib=0))
  amount=number(memory)
  row['used_mib']=None if amount is None or row['used_mib'] is None else row['used_mib']+amount
 except (OSError,ValueError):continue
print(json.dumps(dict(sampled_at=time.time(),devices=list(rows.values()))))
'''

def collect_job(item):
    job_id, node = item
    try:
        if not re.fullmatch(r'\d+', job_id):
            raise ValueError('Invalid allocation ID')
        # Read-only overlapping step inside the existing allocation. No new job/GPU.
        p = subprocess.run(['srun','--jobid='+job_id,'--overlap','--exact',
                            '-N1','-n1','-c1','--time=00:01:00','--immediate=5',
                            'python3','-c',NODE_SCRIPT],
                           capture_output=True,text=True,timeout=15)
        if p.returncode:
            raise RuntimeError('Allocation GPU query unavailable')
        return job_id,json.loads(p.stdout)
    except Exception as e:
        return job_id,dict(error=str(e),devices=[])

def attach(jobs):
    targets = {}
    for job in jobs:
        job['gpu_live'] = dict(devices=[],error='No attributable GPU process')
        if job.get('gpu') == 'CPU only':
            job['gpu_live']['error'] = 'CPU only'
            continue
        node = job.get('node','')
        if re.fullmatch(r'[A-Za-z0-9_.-]+',node):
            targets[job.get('gpu_job_id',job['id'])]=node
        else:
            job['gpu_live']['error'] = 'Multi-node telemetry unavailable'
    if not targets:return
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(collect_job,sorted(targets.items())))
    for job in jobs:
        job_id=job.get('gpu_job_id',job['id'])
        result=results.get(job_id)
        if result is None or job.get('gpu') == 'CPU only':continue
        devices=[d for d in result['devices'] if d['job_id']==job_id]
        job['gpu_live']=dict(devices=devices,sampled_at=result.get('sampled_at'),
                            error=result.get('error') or (None if devices else 'No attributable GPU process'))
