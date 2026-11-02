from pathlib import Path
import sys,os,json,time,gc,hashlib,traceback,shutil
from datetime import datetime, timezone
D=Path(__file__).resolve().parent;R=D.parent
sys.path.insert(0,str(R/'03_Model'))
import pythoncom,win32com.client
import case_calculation as calc
from audits import balances,utilities
from durable_json import write_json
job=json.loads(Path(sys.argv[1]).read_text());state=Path(sys.argv[2]);token=sys.argv[3];pid=None;eqpid=None
A=D
protocol=json.loads((D/'Protocol.json').read_text(encoding='utf-8'))
def stage(name):
 write_json(state,{'token':token,'aspen_pid':pid,'aspen_pids':[p for p in [pid,eqpid] if p],'stage':name,'time':time.time()})
pythoncom.CoInitialize();doc=None;eqdoc=None
try:
 stage('create');doc=win32com.client.DispatchEx(os.environ.get('ASPEN_PROGID','Apwn.Document.40.0'));pid=int(doc.ProcessId);doc.SuppressDialogs=True
 stage('open');doc.InitFromArchive2(str(A/'Input.bkp'));doc.Visible=False
 stage('create_equilibrium');eqdoc=win32com.client.DispatchEx(os.environ.get('ASPEN_PROGID','Apwn.Document.40.0'));eqpid=int(eqdoc.ProcessId);eqdoc.SuppressDialogs=True
 stage('open_equilibrium');eqdoc.InitFromArchive2(str(A/'Equilibrium.bkp'));eqdoc.Visible=False
 for idx,cfg in enumerate(job['cases']):
  rid=cfg['run_id'];started=time.time()
  try:
   stage(rid+':inputs');res=calc.calculate(cfg,doc,lambda x:stage(rid+':'+x),cold_start=(idx==0))
   stage(rid+':audit');bal=balances(res);u=utilities(res)
   stage(rid+':RGibbs')
   eq= res['cracker_thermodynamics']
   eqdoc.Tree.FindNode(r'\Data\Blocks\EQ\Input\TEMP').Value=eq['T_C']
   eqdoc.Tree.FindNode(r'\Data\Blocks\EQ\Input\PRES').Value=eq['P_bar']
   eqdoc.Engine.Run2(False)
   eqstatus=eqdoc.Tree.FindNode(r'\Data\Blocks\EQ\Output\BLKSTAT').Value
   xeq=1-eqdoc.Tree.FindNode(r'\Data\Streams\PRODUCT\Output\MOLEFLOW\MIXED\NH3').Value/100
   eqT=eqdoc.Tree.FindNode(r'\Data\Streams\PRODUCT\Output\TEMP_OUT\MIXED').Value
   eqP=eqdoc.Tree.FindNode(r'\Data\Streams\PRODUCT\Output\PRES_OUT\MIXED').Value
   assert abs(eqT-eq['T_C'])<.001 and abs(eqP-eq['P_bar'])<1e-7,(eqT,eqP,eq)
   eq.update(Aspen_RGibbs_crosscheck_required=False,Aspen_RGibbs_Xeq=xeq,Aspen_RGibbs_block_status=eqstatus,Aspen_RGibbs_actual_Run2_calls=1,Aspen_RGibbs_pid=eqpid,Aspen_RGibbs_margin=xeq-eq['specified_conversion'],Aspen_RGibbs_property_method='PENG-ROB')
   eq.update(Aspen_RGibbs_actual_T_C=eqT,Aspen_RGibbs_actual_P_bar=eqP)
   assert eqstatus==0 and xeq-eq['specified_conversion']>=cfg['cracker_equilibrium_margin_fraction'],eq
   j=res['SOFC']['current_density_A_m2']/10000
   checks={'sampling_envelope':all(v['lower']-1e-10<=cfg[v['key']]<=v['upper']+1e-10 for v in protocol['variables']),'positive_voltage':0<res['SOFC']['cell_voltage_V']<=res['SOFC']['Nernst_V'],'current_density_model_range':0<j<=1,'cracker_hot_feed':res['streams']['03']['TEMP_OUT']>=400,'components_nonnegative':min(x for st in res['streams'].values() for x in st['MOLEFLOW'].values())>=-1e-10}
   assert all(checks.values()),checks
   summary=u['summary'];summary['Run_ID']=rid
   accepted={'Run_ID':rid,'status':'accepted_conditional_model','actual_Aspen_Engine_Run2_calls':len(res['iteration_log']),'aspen_equilibrium_Run2_calls':1,'aspen_pid':pid,'elapsed_s':time.time()-started,'checks':{**bal['checks'],**u['checks'],**checks,**res['checks'],'Aspen_RGibbs_equilibrium':True},'summary':summary,'global_mass_residual_kg_h':bal['global_mass_residual_kg_h'],'global_energy_residual_kW':bal['global_energy_residual_kW'],'element_residuals':bal['element_residual_kmol_atom_h'],'minimum_HX_approaches_K':{n:p['minimum_approach_K'] for n,p in u['temperature_profiles'].items()},'experimental_validation_complete':False,'cost_and_CI_status':'separate evaluation not calculated','warning_review':'batch Aspen history retained; known warnings checked after close'}
   accepted['opened_archive']={'filename':'Input.bkp','sha256':hashlib.sha256((D/'Input.bkp').read_bytes()).hexdigest()}
   accepted['completed_at_UTC']=datetime.now(timezone.utc).isoformat()
   accepted['code_sha256']={name:hashlib.sha256((D/name).read_bytes()).hexdigest() for name in ['batch_worker.py','case_calculation.py','audits.py','durable_json.py']}
   write_json(D/'Results'/f'{rid}.json',{'simulation':res,'acceptance':accepted})
   print(json.dumps({'Run_ID':rid,'accepted':True,'eta':summary['net_AC_efficiency'],'elapsed_s':time.time()-started}),flush=True)
   if rid=='BASELINE' or idx==len(job['cases'])-1:
    stage(rid+':save');doc.SaveAs(str(A/'Snapshots'/('B_'+rid+'_'+job['batch_id']+'.bkp')))
    eqdoc.SaveAs(str(A/'Snapshots'/('EQ_'+rid+'_'+job['batch_id']+'.bkp')))
  except Exception as ex:
   failure={'Run_ID':rid,'config':cfg,'status':'rejected','error':str(ex),'traceback':traceback.format_exc(),'elapsed_s':time.time()-started,'aspen_pid':pid,'batch_id':job['batch_id']}
   diagnostic=getattr(calc,'last_result',None)
   if diagnostic and diagnostic.get('config',{}).get('run_id')==rid:failure['simulation']=diagnostic
   if 'res' in locals() and res.get('config',{}).get('run_id')==rid:failure['simulation']=res
   failure['actual_Aspen_Engine_Run2_calls']=len(failure.get('simulation',{}).get('iteration_log',[]))
   write_json(D/'Results'/f'{rid}_FAILED.json',failure)
   print(json.dumps(failure),flush=True)
   try:
    stage(rid+':save_failure');doc.SaveAs(str(A/'Snapshots'/('FAILED_'+rid+'_'+job['batch_id']+'.bkp')))
   except Exception as save_ex:print('Failure snapshot: '+str(save_ex),flush=True)
   # Abort batch on failure; controller restarts a clean owned instance for remaining cases.
   raise
finally:
 try:stage('close')
 except OSError as ex:print('Close state logging: '+str(ex),flush=True)
 gc.collect()
 if doc:
  try:doc.Quit()
  except Exception as ex:print('Close: '+str(ex),flush=True)
 if eqdoc:
  try:eqdoc.Quit()
  except Exception as ex:print('Equilibrium close: '+str(ex),flush=True)
 doc=None;eqdoc=None;gc.collect();pythoncom.CoUninitialize()
