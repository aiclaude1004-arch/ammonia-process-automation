from pathlib import Path
import json,sys,subprocess,time,uuid,ctypes,hashlib
from durable_json import write_json
D=Path(__file__).resolve().parent
phase=sys.argv[1]; assert phase in ['screen','campaign']
cases=json.loads((D/('Screen.json' if phase=='screen' else 'Candidates.json')).read_text(encoding='utf-8'))
if phase=='campaign':
 review=json.loads((D/'Pilot_Review.json').read_text(encoding='utf-8'));assert review['ready_for_campaign'],'Reviewed pilot/screen required'
target=1000 if phase=='campaign' else len(cases)
batch_size=int(sys.argv[2]) if len(sys.argv)>2 else 25
def accepted(c):return (D/'Results'/f"{c['run_id']}.json").exists()
def failed(c):return (D/'Results'/f"{c['run_id']}_FAILED.json").exists()
pending=[c for c in cases if not accepted(c) and not failed(c)]
k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.restype=ctypes.c_void_p;k.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint];k.CloseHandle.argtypes=[ctypes.c_void_p];k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint]
batch_no=0
while pending:
 if (D/'STOP_AFTER_BATCH').exists():print('PAUSED_AFTER_BATCH',flush=True);break
 count=sum(accepted(c) for c in cases)
 if phase=='campaign' and count>=target:break
 batch_no+=1;batch=pending[:min(batch_size,target-count)];batchid=phase.upper()+'_'+str(batch_no)+'_'+uuid.uuid4().hex[:6];token=uuid.uuid4().hex
 job=D/'Logs'/f'{batchid}.json';job.write_text(json.dumps({'batch_id':batchid,'cases':batch}));state=D/'Logs'/f'{batchid}.state.json'
 start=time.monotonic();last=None;handles={};pid=None
 with (D/'Logs'/f'{batchid}.log').open('w',encoding='utf-8') as out:
  proc=subprocess.Popen([sys.executable,'-X','utf8',str(D/'batch_worker.py'),str(job),str(state),token],stdout=out,stderr=subprocess.STDOUT,cwd=D)
  while proc.poll() is None:
   time.sleep(.5)
   if state.exists():
    try:s=json.loads(state.read_text())
    except (ValueError,OSError):continue
    assert s['token']==token
    if s['stage']!=last:last=s['stage'];start=time.monotonic()
    for owned_pid in s.get('aspen_pids',[]):
     if owned_pid not in handles:
      handle=k.OpenProcess(0x100001,False,owned_pid)
      if not handle:raise RuntimeError('Cannot establish owned process handle')
      handles[owned_pid]=handle
    pid=s.get('aspen_pid')
   if time.monotonic()-start>(300 if last in ['open','open_equilibrium'] else 180):
    for handle in handles.values():k.TerminateProcess(handle,124)
    proc.kill();proc.wait();break
  clean=True
  for handle in handles.values():
   closed=k.WaitForSingleObject(handle,10000)==0;clean=clean and closed;k.CloseHandle(handle)
  supervisor={'batch_id':batchid,'worker_exit':proc.returncode,'clean_Aspen_exit':clean,'owned_Aspen_pid':pid,'owned_Aspen_pids':list(handles),'last_stage':last}
  (D/'Logs'/f'{batchid}_supervisor.json').write_text(json.dumps(supervisor,indent=2))
  if not clean:raise RuntimeError('Owned Aspen process did not close; campaign paused')
  if proc.returncode and not any(failed(c) for c in batch):raise RuntimeError('Batch failed without a recorded case failure; campaign paused')
 pending=[c for c in cases if not accepted(c) and not failed(c)]
 count=sum(accepted(c) for c in cases)
 progress={'phase':phase,'requested':target,'accepted':count,'rejected':sum(failed(c) for c in cases),'remaining':max(0,target-count) if phase=='campaign' else len(pending),'untried_candidates':len(pending)}
 write_json(D/('Screen_Status.json' if phase=='screen' else 'Campaign_Status.json'),progress);print(json.dumps(progress),flush=True)
 if phase=='campaign':write_json(D/'Conditions.json',[c for c in cases if accepted(c)])
if phase=='campaign':assert sum(accepted(c) for c in cases)==target,'Candidate pool exhausted before 1000 accepted points'
print('FINISHED',flush=True)
