from electrochemistry import stack,thermo,R
from sofc_model import heat_balance
import time,pythoncom,math
def node(p):
 n=doc.Tree.FindNode(p)
 if n is None:raise ValueError('Missing node '+p)
 return n
def get(p):return node(p).Value
def put(p,v):node(p).Value=v
def mol(sn,c):return get(fr'\Data\Streams\{sn}\Output\MOLEFLOW\MIXED\{c}') or 0.
def feed(sn,c,v):put(fr'\Data\Streams\{sn}\Input\FLOW\MIXED\{c}',v)
def walk(n,depth=0):
 out={'name':n.Name,'value':n.Value}
 if depth<4:
  try:out['children']=[walk(x,depth+1) for x in n.Elements]
  except Exception:pass
 return out

def calculate(cfg,document,stage_callback,cold_start=False):
 global doc,stage,last_result
 doc=document;stage=stage_callback;last_result=None
 put(r'\Data\Blocks\R3\Input\CONV\1',cfg['ice_NH3_conversion'])
 put(r'\Data\Blocks\R3\Input\CONV\2',cfg['ice_H2_conversion'])
 # All independent operating conditions have one source: this configuration.
 for bn in ['R2','H1']:
  put(fr'\Data\Blocks\{bn}\Input\TEMP',cfg['temperature_C']);put(fr'\Data\Blocks\{bn}\Input\PRES',cfg['pressure_bar'])
 put(r'\Data\Blocks\M2\Input\PRES',cfg['pressure_bar'])
 applied=[]
 put(r'\Data\Blocks\R1\Input\CONV\1',cfg['cracker_conversion'])
 put(r'\Data\Blocks\R1\Input\PRES',cfg['cracker_pressure_bar'])
 put(r'\Data\Blocks\R5\Input\TEMP',cfg['cracker_burner_temperature_C'])
 assert cfg['cracker_burner_temperature_C']-cfg['cracker_temperature_C']>=cfg['cracker_minimum_heat_approach_K']
 burner_fuel=51.303966770621*cfg['cracker_feed_kmol_h']/100
 try:
  old_flow=mol('02',1);old_burn=mol('27',1);old_T=get(r'\Data\Streams\03\Output\TEMP_OUT\MIXED')
  old_x=1-mol('03',1)/old_flow
  def product_h(T,x):return (1-x)*thermo('NH3',T+273.15)[0]+1.5*x*thermo('H2',T+273.15)[0]+.5*x*thermo('N2',T+273.15)[0]
  correction=cfg['cracker_feed_kmol_h']*(product_h(cfg['cracker_temperature_C'],cfg['cracker_conversion'])-product_h(old_T,old_x))/3600
  unit_heat=-get(r'\Data\Blocks\R5\Output\QCALC')*1163/old_burn
  burner_fuel=old_burn*cfg['cracker_feed_kmol_h']/old_flow+correction/unit_heat
 except (ValueError,ZeroDivisionError,TypeError):pass
 last_burner=None;last_temp=None
 applied.append({'key':'cracker_pressure_bar','path':r'\Data\Blocks\R1\Input\PRES','requested':cfg['cracker_pressure_bar']})
 applied.append({'key':'cracker_conversion','path':r'\Data\Blocks\R1\Input\CONV\1','requested':cfg['cracker_conversion']})
 for key,path in [
  ('pressure_bar',r'\Data\Blocks\H2\Input\PRES'),
  ('pressure_bar',r'\Data\Blocks\R3\Input\PRES'),
  ('oxygen_utilization',r'\Data\Blocks\S1\Input\FRACS\04\MIXED\4'),
  ('NO_capture_fraction',r'\Data\Blocks\S2\Input\FRACS\37\MIXED\7'),
  ('NH3_recovery_fraction',r'\Data\Blocks\S4\Input\FRACS\44\MIXED\1'),
  ('fuel_preheat_C',r'\Data\Blocks\H2\Input\TEMP'),
  ('norr_feed_C',r'\Data\Blocks\H3\Input\TEMP'),
  ('exhaust_cooling_C',r'\Data\Blocks\H6\Input\TEMP'),
  ('orc_high_pressure_bar',r'\Data\Blocks\P1\Input\PRES')]:
  put(path,cfg[key]);applied.append({'key':key,'path':path,'requested':cfg[key]})
 put(r'\Data\Blocks\HX4\Input\UA',cfg['HX4_UA_cal_s_K'])
 put(r'\Data\Blocks\HX4\Input\PMAXIT',100)
 put(r'\Data\Convergence\Conv-Options\Input\TOL',1e-8)
 # S1 oxygen fraction and the external SOFC air calculation share one input.
 recycle=mol('46',1);target=cfg['cracker_feed_kmol_h'];input_fuel={'H2':target*1.5*cfg['cracker_conversion'],'NH3':target*(1-cfg['cracker_conversion']),'N2':target*.5*cfg['cracker_conversion'],'H2O':0.}
 logs=[]
 for it in range(30):
  T=get(r'\Data\Blocks\R2\Input\TEMP');P=get(r'\Data\Blocks\R2\Input\PRES')
  fc=stack(input_fuel,cfg['fuel_utilization'],cfg['active_area_m2'],T,P,cfg['oxygen_utilization'],cfg['inverter_efficiency'])
  put(r'\Data\Blocks\R2\Input\CONV\2',fc['NH3_conversion'])
  feed('01',1,target-recycle);feed('16',4,fc['air_O2_kmol_h']);feed('16',3,fc['air_N2_kmol_h'])
  ice_o2=cfg['ice_lambda']*(.75*(cfg['ice_fresh_NH3_kmol_h']+fc['anode_out_kmol_h']['NH3'])+.5*fc['anode_out_kmol_h']['H2'])
  feed('07',1,cfg['ice_fresh_NH3_kmol_h'])
  feed('09',4,ice_o2);feed('09',3,ice_o2*79/21)
  feed('27',1,burner_fuel)
  burner_o2=burner_fuel*.762*cfg['cracker_burner_lambda']
  feed('29',4,burner_o2);feed('29',3,burner_o2*79/21)
  no=.02*(cfg['ice_NH3_conversion']*(cfg['ice_fresh_NH3_kmol_h']+fc['anode_out_kmol_h']['NH3'])+burner_fuel)*cfg['NO_capture_fraction']
  feed('39',5,water_actual+(no-last_no_estimate)*11 if it>0 else no*11)
  last_no_estimate=no
  if it==0 and cold_start:stage('reinit');doc.Reinit()
  # Hidden automation instance: synchronous execution prevents reading an
  # incomplete block status before an asynchronous run becomes observable.
  # The independent controller still enforces the 180-second watchdog.
  stage('run_'+str(it));doc.Engine.Run2(False)
  while doc.Engine.IsRunning:time.sleep(.2);pythoncom.PumpWaitingMessages()
  stage('read_'+str(it))
  statuses={x.Name:get(fr'\Data\Blocks\{x.Name}\Output\BLKSTAT') for x in node(r'\Data\Blocks').Elements}
  if any(v!=0 for v in statuses.values()):raise RuntimeError('Block failure '+str(statuses))
  actual={'NH3':mol('03',1),'H2':mol('03',2),'N2':mol('03',3),'H2O':mol('03',5)}
  observed=stack(actual,cfg['fuel_utilization'],cfg['active_area_m2'],get(r'\Data\Blocks\R2\Input\TEMP'),get(r'\Data\Blocks\R2\Input\PRES'),cfg['oxygen_utilization'],cfg['inverter_efficiency'])
  errors=[abs(mol('39',5)-mol('37',7)*11),abs(mol('02',1)-target),abs(mol('06',1)-observed['anode_out_kmol_h']['NH3']),abs(mol('04',4)-observed['O2_consumed_kmol_h']),abs(mol('06',2)-observed['anode_out_kmol_h']['H2'])]
  cracker_T=get(r'\Data\Streams\03\Output\TEMP_OUT\MIXED')
  temperature_error=cfg['cracker_temperature_C']-cracker_T
  logs.append({'iteration':it,'maximum_molar_error_kmol_h':max(errors),'voltage_V':observed['cell_voltage_V'],'cracker_temperature_C':cracker_T,'cracker_temperature_error_K':temperature_error,'burner_fuel_kmol_h':burner_fuel})
  fc=observed
  if max(errors)<1e-6 and abs(temperature_error)<=cfg['cracker_temperature_tolerance_K']:break
  # Fired heat is changed by actual fuel and stoichiometrically linked air.
  # The R5->R1 heat stream remains the sole cracker heat supply.
  required_delta_kW=sum(actual[sp]*(thermo(sp,cfg['cracker_temperature_C']+273.15)[0]-thermo(sp,cracker_T+273.15)[0]) for sp in ['NH3','H2','N2'])/3600
  heat_per_fuel=-get(r'\Data\Blocks\R5\Output\QCALC')*1163/burner_fuel
  assert heat_per_fuel>0
  next_burner=burner_fuel+required_delta_kW/heat_per_fuel
  if last_burner is not None and abs(burner_fuel-last_burner)>1e-6:
   slope=(cracker_T-last_temp)/(burner_fuel-last_burner)
   if slope>1:next_burner=burner_fuel+temperature_error/slope
  last_burner,last_temp=burner_fuel,cracker_T
  burner_fuel=max(burner_fuel*.8,min(burner_fuel*1.2,next_burner))
  assert 0<burner_fuel<100,'Fired fuel exceeds declared exploratory limit'
  input_fuel=actual;recycle=mol('46',1)
  # Next iteration's water estimate from actual capture converges with the NH3 recycle.
  water_actual=mol('37',7)*11
 else:raise RuntimeError('Coupling did not converge')
 streams={}
 for sn in [x.Name for x in node(r'\Data\Streams').Elements if x.Name!='33']:
  streams[sn]={k:get(fr'\Data\Streams\{sn}\Output\{k}\MIXED') for k in ['TEMP_OUT','PRES_OUT','MOLEFLMX','MASSFLMX','HMX_FLOW','VFRAC_OUT','VOLFLMX']}
  streams[sn]['MOLEFLOW']={str(c):mol(sn,c) for c in range(1,10)}
  for kind in ['MASSFLOW']:
   streams[sn][kind]={str(c):get(fr'\Data\Streams\{sn}\Output\{kind}\MIXED\{c}') for c in range(1,10)}
  for kind,flow,total in [('MOLEFRAC','MOLEFLOW','MOLEFLMX'),('MASSFRAC','MASSFLOW','MASSFLMX')]:
   streams[sn][kind]={str(c):streams[sn][flow][str(c)]/streams[sn][total] if streams[sn][total] else None for c in range(1,10)}
 blocks={}
 for bn in statuses:
  blocks[bn]={}
  for k in ['BLKSTAT','QCALC','WNET','B_TEMP','B_PRES']:
   n=doc.Tree.FindNode(fr'\Data\Blocks\{bn}\Output\{k}');blocks[bn][k]=n.Value if n is not None else None
 h=lambda sn:streams[sn]['HMX_FLOW']*1163
 loss=(actual['H2']+1.5*actual['NH3'])*241826/3600*.01
 heat=heat_balance(h('03')+h('53'),h('06')+h('19'),fc['SOFC_DC_kW'],loss)
 heat['heat_loss_assumption_kW']=loss
 last_result={'config':cfg,'streams':streams,'blocks':blocks,'SOFC':fc,'iteration_log':logs,'stack_heat':heat}
 assert heat['external_heat_required_kW']<=cfg['thermal_heater_capacity_kW'],f"SOFC heater demand {heat['external_heat_required_kW']} exceeds capacity {cfg['thermal_heater_capacity_kW']} kW"
 assert heat['heat_export_kW']<=cfg['thermal_dump_capacity_kW'],f"SOFC heat export {heat['heat_export_kW']} exceeds capacity {cfg['thermal_dump_capacity_kW']} kW"
 assert abs(get(r'\Data\Blocks\HX4\Input\UA')-cfg['HX4_UA_cal_s_K'])<1e-6
 checks={'blocks_normal':all(v==0 for v in statuses.values()),'actual_feed_linked':max(errors)<1e-6,'fixed_UA':True,'actual_temperature_linked':abs(streams['06']['TEMP_OUT']-fc['temperature_C'])<1e-5,'actual_pressure_linked':abs(streams['06']['PRES_OUT']-P)<1e-5,'thermal_control_within_capacity':True}
 for a in applied:a['readback']=get(a['path'])
 # Aspen serializes these input nodes to about 11 significant decimal digits.
 # E.g. 153.6651943328078 C reads back 153.66519433 C; physical tolerances
 # for mass/energy/temperature/pressure are unchanged.
 for a in applied:a['serialization_error']=a['readback']-a['requested']
 checks['input_readback']=all(abs(a['serialization_error'])<=5e-11*max(1.,abs(a['requested'])) for a in applied)
 checks['cracker_conversion_actual']=abs(1-mol('03',1)/mol('02',1)-cfg['cracker_conversion'])<1e-8
 assert abs(streams['02']['MOLEFLOW']['1']/streams['02']['MOLEFLMX']-1)<1e-9,'Pure NH3 equilibrium screen no longer applicable'
 eqT=streams['03']['TEMP_OUT']+273.15;eqP=streams['03']['PRES_OUT']
 dg=1.5*thermo('H2',eqT)[2]+.5*thermo('N2',eqT)[2]-thermo('NH3',eqT)[2]
 K=math.exp(-dg/R/eqT)
 xeq=math.sqrt(K/(K+1.5**1.5*.5**.5*eqP/1.01325))
 checks['cracker_temperature_control']=abs(streams['03']['TEMP_OUT']-cfg['cracker_temperature_C'])<=cfg['cracker_temperature_tolerance_K']
 checks['cracker_pressure_actual']=abs(eqP-cfg['cracker_pressure_bar'])<1e-7
 checks['cracker_equilibrium_screen']=xeq-cfg['cracker_conversion']>=cfg['cracker_equilibrium_margin_fraction']
 checks['cracker_heat_source_approach']=streams['32']['TEMP_OUT']-streams['03']['TEMP_OUT']>=cfg['cracker_minimum_heat_approach_K']
 checks['oxygen_fraction_linked']=abs(mol('04',4)/mol('53',4)-cfg['oxygen_utilization'])<1e-8
 checks['NO_capture_fraction_linked']=abs(mol('37',7)/mol('35',7)-cfg['NO_capture_fraction'])<1e-8
 checks['NH3_recovery_fraction_linked']=abs(mol('44',1)/mol('43',1)-cfg['NH3_recovery_fraction'])<1e-8
 result={'config':cfg,'applied_inputs':applied,'iteration_log':logs,'blocks':blocks,'streams':streams,'SOFC':fc,'stack_heat':heat,'checks':checks,'production_release':False,'stage2_model':'parametric ICE and explicit untreated N2O/slip; no experimentally fitted engine map'}
 result['cracker_thermodynamics']={'T_C':streams['03']['TEMP_OUT'],'P_bar':eqP,'specified_conversion':cfg['cracker_conversion'],'ideal_gas_equilibrium_conversion':xeq,'equilibrium_margin_fraction':xeq-cfg['cracker_conversion'],'heat_source_approach_K':streams['32']['TEMP_OUT']-streams['03']['TEMP_OUT'],'actual_burner_fuel_kmol_h':mol('27',1),'kinetics_validated':False,'Aspen_RGibbs_crosscheck_required':True}
 last_result=result
 assert all(checks.values()),str(checks)
 return result
