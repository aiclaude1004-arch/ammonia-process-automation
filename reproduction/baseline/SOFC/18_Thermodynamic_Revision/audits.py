from pathlib import Path
import json,math,sys
from functools import lru_cache
ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT/'03_Model'),str(ROOT/'Work/property_deps')]
from electrochemistry import thermo,bisect,F,R
from CoolProp.CoolProp import PropsSI

def organic_enthalpy(stream, pressure_Pa=None):
    """Pure R245fa: quality resolves a two-phase P,T state uniquely."""
    p=stream['PRES_OUT']*1e5 if pressure_Pa is None else pressure_Pa
    t=stream['TEMP_OUT']+273.15
    q=stream['VFRAC_OUT']
    assert 0<=q<=1
    assert abs(stream['MOLEFRAC']['6']-1)<1e-10,'Quality flash requires pure R245fa'
    if 0<q<1:
        assert abs(PropsSI('T','P',p,'Q',q,'R245fa')-t)<.001,'Aspen/CoolProp saturation temperatures disagree'
        return PropsSI('H','P',p,'Q',q,'R245fa')
    try:return PropsSI('H','T',t,'P',p,'R245fa')
    except ValueError as ex:
        if 'Saturation pressure' not in str(ex):raise
        assert abs(PropsSI('T','P',p,'Q',q,'R245fa')-t)<.001
        return PropsSI('H','P',p,'Q',q,'R245fa')

def balances(d):
    g=json.loads((ROOT/'02_Baseline/Original_Graph.json').read_text(encoding='utf-8'))
    edges=[dict(e) for e in g['edges'] if e['Type']=='material']
    for e in edges:
        if e['Stream_Name']=='17':e['To_Node']='HX4'
        if e['Stream_Name']=='21':e['To_Node']='HX4'
    edges.extend([{'Stream_Name':'52','From_Node':'HX4','To_Node':'OUT_HX4'},
                  {'Stream_Name':'53','From_Node':'HX4','To_Node':'S1'}])
    for e in edges:
        if e['Stream_Name']=='34':e['To_Node']='H6'
    edges.append({'Stream_Name':'54','From_Node':'H6','To_Node':'F1'})
    s=d['streams'];b=d['blocks']
    incoming=[e['Stream_Name'] for e in edges if e['From_Node'].startswith('IN')]
    outgoing=[e['Stream_Name'] for e in edges if e['To_Node'].startswith('OUT')]
    q={n:0. if n.startswith('HX') else (v['QCALC'] or 0)*1163 for n,v in b.items()}
    w={n:v['WNET'] or 0. for n,v in b.items()}
    h=lambda sn:s[sn]['HMX_FLOW']*1163
    block_balances={}
    for n in b:
        ins=[e['Stream_Name'] for e in edges if e['To_Node']==n]
        outs=[e['Stream_Name'] for e in edges if e['From_Node']==n]
        block_balances[n]={
            'mass_kg_h':sum(s[x]['MASSFLMX'] for x in outs)-sum(s[x]['MASSFLMX'] for x in ins),
            'enthalpy_kW':sum(h(x) for x in outs)-sum(h(x) for x in ins)-q[n]-w[n]}
    atoms={'N':[1,0,2,0,0,0,1,1,2],'H':[3,2,0,0,2,3,0,0,0],
           'O':[0,0,0,2,1,0,1,2,1],'C':[0,0,0,0,0,3,0,0,0],'F':[0,0,0,0,0,5,0,0,0]}
    element={el:sum(sum(s[sn]['MOLEFLOW'][str(i+1)]*c for i,c in enumerate(cs)) for sn in outgoing)
                 -sum(sum(s[sn]['MOLEFLOW'][str(i+1)]*c for i,c in enumerate(cs)) for sn in incoming)
             for el,cs in atoms.items()}
    mass=sum(s[x]['MASSFLMX'] for x in outgoing)-sum(s[x]['MASSFLMX'] for x in incoming)
    energy=sum(h(x) for x in outgoing)-sum(h(x) for x in incoming)-sum(q.values())-sum(w.values())
    hx={}
    for name,hi,ho,ci,co in [('HX1','19','20','10','11'),('HX2','14','15','23','24'),('HX3','20','21','24','25'),('HX4','21','52','17','53')]:
        hx[name]={'hot_duty_kW':h(hi)-h(ho),'cold_duty_kW':h(co)-h(ci),
                  'terminal_approach_K':[s[hi]['TEMP_OUT']-s[co]['TEMP_OUT'],s[ho]['TEMP_OUT']-s[ci]['TEMP_OUT']],
                  'internal_profile_validation':'see corresponding utility audit for independently sampled profiles; not a hardware rating'}
    checks={'all_blocks_normal':all(x['BLKSTAT']==0 for x in b.values()),
            'global_mass':abs(mass)<.001,'global_energy':abs(energy)<.001,
            'elements':max(map(abs,element.values()))<1e-4,
            'block_mass':max(abs(x['mass_kg_h']) for x in block_balances.values())<.001,
            'block_energy':max(abs(x['enthalpy_kW']) for x in block_balances.values())<.001,
            'HX_energy':all(abs(v['hot_duty_kW']-v['cold_duty_kW'])<.001 for v in hx.values()),
            'HX_terminal_approaches':all(min(v['terminal_approach_K'])>=20 for v in hx.values()),
            'ORC_inlet_dry':s['25']['VFRAC_OUT']>=.999,'ORC_exit_quality':s['26']['VFRAC_OUT']>=.85}
    report={'checks':checks,'global_mass_residual_kg_h':mass,'global_energy_residual_kW':energy,
            'element_residual_kmol_atom_h':element,'block_balances':block_balances,'heat_exchangers':hx,
            'raw_Aspen_heat_includes_electrical_energy_until_external_partition':True,
            'independent_experimental_validation':False,'released_for_training':False,
            'warning':'Initialization and property warnings require separate log review; block status and independent balances are checked here.'}
    assert all(checks.values()), str(checks)
    return report

def utilities(d):
    mode=d['config']['run_id']
    s=d['streams'];b=d['blocks'];fc=d['SOFC']
    h=lambda n:s[n]['HMX_FLOW']*1163
    mol=lambda n,c:s[n]['MOLEFLOW'][str(c)]
    q={n:(0. if n.startswith('HX') else (v['QCALC'] or 0)*1163) for n,v in b.items()}
    w={n:v['WNET'] or 0 for n,v in b.items()}
    T=lambda n:s[n]['TEMP_OUT']
    species={1:'NH3',2:'H2',3:'N2',4:'O2',5:'H2O',7:'NO',8:'NO2',9:'N2O'}
    @lru_cache(maxsize=None)
    def gas_h(n,t):return sum(mol(n,c)*thermo(sp,t+273.15)[0] for c,sp in species.items())/3600
    @lru_cache(maxsize=None)
    def organic_h(n,p):return organic_enthalpy(s[n],p)
    def temperature_path(ni,no,f,organic=False):
        p=s[ni]['PRES_OUT']*1e5
        if organic:
            a=organic_h(ni,p)
            z=organic_h(no,p)
            return PropsSI('T','H',a+(z-a)*f,'P',p,'R245fa')-273.15
        a=gas_h(ni,T(ni));z=gas_h(ni,T(no));target=a+(z-a)*f
        if f==0:return T(ni)
        if f==1:return T(no)
        return bisect(lambda t:gas_h(ni,t)-target,min(T(ni),T(no)),max(T(ni),T(no)),1e-7)
    profiles={}
    for name,hi,ho,ci,co in [('HX1','19','20','10','11'),('HX2','14','15','23','24'),('HX3','20','21','24','25'),('HX4','21','52','17','53')]:
        rows=[]
        for i in range(101):
            f=i/100;th=temperature_path(hi,ho,f);tc=temperature_path(ci,co,1-f,name in ['HX2','HX3'])
            rows.append([f,th,tc,th-tc])
        profiles[name]={'minimum_approach_K':min(r[3] for r in rows),'rows':rows,
                        'method':'101 equal fractional-duty points; NASA ideal gas / CoolProp HEOS at Aspen endpoints',
                        'same_EOS_as_Aspen':False}
    # H5 condenser: water flows countercurrently, 20->25 C. Design assumption.
    rows=[]
    for i in range(101):
        f=i/100;th=temperature_path('26','22',f,True);tc=25-5*f
        rows.append([f,th,tc,th-tc])
    profiles['H5']={'minimum_approach_K':min(r[3] for r in rows),'rows':rows,
                    'coolant_in_C':20,'coolant_out_C':25,'method':'CoolProp R245fa H-P flash + constant-cp cooling water'}
    cp_orc={}
    for name,ni,no in [('pump','22','23'),('evaporator','23','24'),('superheater','24','25'),('turbine','25','26'),('condenser','26','22')]:
        cpdh=s[ni]['MASSFLMX']/3600*(organic_h(no,s[no]['PRES_OUT']*1e5)-organic_h(ni,s[ni]['PRES_OUT']*1e5))/1000
        dh=h(no)-h(ni)
        cp_orc[name]={'Aspen_deltaH_kW':dh,'CoolProp_deltaH_kW':cpdh,'relative_difference':abs(cpdh-dh)/max(abs(dh),1e-8)}
    # Explicit electrical/thermal partition of existing surrogate blocks.
    lhv_h2=thermo('H2',298.15)[0]+.5*thermo('O2',298.15)[0]-thermo('H2O',298.15)[0]
    lhv_nh3=thermo('NH3',298.15)[0]-1.5*thermo('H2O',298.15)[0]
    # Standard elemental formation enthalpies N2 and O2 are zero by definition.
    # Do not extrapolate GRI N2 polynomial below its 300 K lower bound.
    ice_fuel=(mol('13',1)*lhv_nh3+mol('13',2)*lhv_h2)/3600
    ice_shaft=d['config']['ice_brake_efficiency']*ice_fuel
    no=mol('40',7)-mol('41',7);no2=mol('40',8)-mol('41',8)
    her_h2=mol('41',2)-mol('40',2)
    charge_kmol_e=5*no+7*no2+2*her_h2
    fe=(5*no+7*no2)/charge_kmol_e
    norr_dc=charge_kmol_e*F/3600*2.62
    norr_ac=norr_dc/.95
    cap=s['37']['MASSFLMX']*2;rec=s['44']['MASSFLMX']*2
    motor_shaft=sum(max(v,0) for v in w.values());motor_ac=motor_shaft/.95
    tur=-w['T1'];tur_ac=.95*tur
    special={'R1','R5','R2','H1','S1','R3','R4'}
    other_heat={n:max(v,0) for n,v in q.items() if n not in special}
    other_cool={n:max(-v,0) for n,v in q.items() if n not in special}
    thermal_heater=d['stack_heat']['external_heat_required_kW']
    stack_reject=-(q['R2']+q['H1']+q['S1'])-fc['SOFC_DC_kW']+thermal_heater
    ice_reject=-q['R3']-ice_shaft
    norr_reject=norr_dc-q['R4']
    cool_base=stack_reject+ice_reject+norr_reject+sum(other_cool.values())+cap+rec
    cool_base+=fc['inverter_loss_kW']+ice_shaft*.04+tur*.05+motor_ac-motor_shaft+norr_ac-norr_dc
    # Explicit two-level utility boundary. Water 20->25 C; glycol 0->5 C.
    # Refrigeration evaporation -20 C / condensation 45 C; second-law AC COP fraction 0.45 is an assumption.
    graph=json.loads((ROOT/'02_Baseline/Original_Graph.json').read_text(encoding='utf-8'))
    edges=[dict(e) for e in graph['edges'] if e['Type']=='material']
    for e in edges:
        if e['Stream_Name']=='34':e['To_Node']='H6'
    edges.append({'Stream_Name':'54','From_Node':'H6','To_Node':'F1','Type':'material'})
    utility_checks={};cold_blocks=[];warm_blocks=[]
    for bn,load in other_cool.items():
        if load<1e-5:continue
        outs=[e['Stream_Name'] for e in edges if e['From_Node']==bn]
        hotmin=min(T(x) for x in outs)
        if bn=='H5':
            utility_checks[bn]={'load_kW':load,'utility':'water_20_to_25','min_approach_K':profiles['H5']['minimum_approach_K'],'method':'101 point profile'};warm_blocks.append(bn)
        elif hotmin>=45:
            utility_checks[bn]={'load_kW':load,'utility':'water_20_to_25','min_approach_lower_bound_K':hotmin-25,'method':'entire hot path >= outlet T; entire coolant <=25 C'};warm_blocks.append(bn)
        else:
            utility_checks[bn]={'load_kW':load,'utility':'glycol_0_to_5','min_approach_lower_bound_K':hotmin-5,'method':'entire hot path >= outlet T; entire coolant <=5 C'};cold_blocks.append(bn)
    # Device cooling interfaces are declared operating assumptions, not measured equipment data.
    for bn,load,temp in [('NORR_cell',norr_reject,35.),('ICE_jacket',ice_reject,90.),('SOFC_loss_and_dump',stack_reject,fc['temperature_C'])]:
        utility_checks[bn]={'load_kW':load,'utility':'glycol_0_to_5' if bn=='NORR_cell' else 'water_20_to_25','min_approach_lower_bound_K':temp-(5 if bn=='NORR_cell' else 25),'assumed_cooling_interface_C':temp}
    elec_losses=fc['inverter_loss_kW']+ice_shaft*.04+tur*.05+motor_ac-motor_shaft+norr_ac-norr_dc
    cold_base=sum(other_cool[x] for x in cold_blocks)+norr_reject+cap+rec+elec_losses
    utility_checks['electrical_and_separation_losses']={'load_kW':cap+rec+elec_losses,'utility':'glycol_0_to_5','min_approach_lower_bound_K':30.,'assumed_cooling_interface_C':35.}
    k_cold=150000/(1030*.75*.95*3600*5)
    cold_pump=k_cold*cold_base/(1-k_cold)
    cold_load=cold_base+cold_pump
    cop_carnot=(273.15-20)/(45-(-20));cop=.45*cop_carnot
    chiller_ac=cold_load/cop;chiller_condenser=cold_load+chiller_ac
    warm_base=cool_base-cold_base+chiller_condenser
    k_warm=150000/(1000*.75*.95*4180*5)
    warm_pump=k_warm*warm_base/(1-k_warm)
    cool_pump=cold_pump+warm_pump
    utility_checks['chiller_condenser']={'load_kW':chiller_condenser,'utility':'water_20_to_25','min_approach_lower_bound_K':20.}
    utility_checks['chiller_evaporator']={'load_kW':cold_load,'utility':'refrigerant_minus20','min_approach_K':20.,'required_approach_K':20.,'reason':'conservative 20 K approach also enforced on refrigeration interface'}
    # Refrigeration and process utility interfaces both satisfy the declared 20 K requirement.
    net=fc['SOFC_AC_kW']+ice_shaft*.96+tur_ac-motor_ac-norr_ac-cap-rec-sum(other_heat.values())-thermal_heater-cool_pump-chiller_ac
    
    fuel_input=sum(mol(n,1) for n in ['01','07','27'])*lhv_nh3/3600
    graph=json.loads((ROOT/'02_Baseline/Original_Graph.json').read_text(encoding='utf-8'))
    edges=[e for e in graph['edges'] if e['Type']=='material']
    ins=[e['Stream_Name'] for e in edges if e['From_Node'].startswith('IN')]
    outs=[e['Stream_Name'] for e in edges if e['To_Node'].startswith('OUT') and e['Stream_Name']!='21']+['52']
    dh_global=sum(h(n) for n in outs)-sum(h(n) for n in ins)
    energy_residual=dh_global+net+cool_base+cool_pump+chiller_ac
    orc_heat=h('25')-h('23');orc_net=tur_ac-w['P1']/.95
    sec=norr_ac/(no*17.03052) if no else None
    checks={'all_cooling_interfaces_pass':all(x.get('min_approach_lower_bound_K',x.get('min_approach_K',0))>=x.get('required_approach_K',20)-1e-5 for x in utility_checks.values()),'COP_below_Carnot':0<cop<cop_carnot,'HX_sampled_pinch_20K':all(v['minimum_approach_K']>=20-1e-5 for v in profiles.values()),
            'ORC_independent_EOS_heat_within_5pct':all(v['relative_difference']<.05 for key,v in cp_orc.items() if key!='pump'),
            'ICE_rejected_heat_nonnegative':ice_reject>=0,'NORR_rejected_heat_nonnegative':norr_reject>=0,
            'SOFC_rejected_heat_nonnegative':stack_reject>=0,'cooling_nonnegative':cool_base>0,
            'full_energy_allocation':abs(energy_residual)<.002,'FE_matches_selected_point':abs(fe-.8337)<1e-6,
            'NORR_water_available':mol('41',5)>=0,'ORC_net_positive':orc_net>0,
            'efficiency_between_zero_and_one':0<net/fuel_input<1,
            'cracker_burner_duties_match':abs(q['R1']+q['R5'])<.001}
    summary={'Run_ID':'REVISED_'+mode.upper(),'model_label_status':'conditional_research_model_NOT_validated_training_truth',
     'Net_AC_kW':net,'Fuel_LHV_kW':fuel_input,'net_AC_efficiency':net/fuel_input,
     'SOFC_AC_kW':fc['SOFC_AC_kW'],'ICE_shaft_kW':ice_shaft,'ICE_AC_kW':ice_shaft*.96,
     'ICE_shaft_efficiency_assumption':.45,'ICE_H2_LHV_fraction':mol('13',2)*lhv_h2/3600/ice_fuel,
     'ICE_inlet_water_mole_fraction':mol('13',5)/s['13']['MOLEFLMX'],
     'ORC_net_AC_kW':orc_net,'ORC_heat_input_kW':orc_heat,'ORC_efficiency':orc_net/orc_heat,
     'Motor_AC_kW':motor_ac,'NORR_DC_kW':norr_dc,'NORR_AC_kW':norr_ac,
     'NORR_FE_actual':fe,'NORR_SEC_AC_kWh_kgNH3':sec,'NORR_NH3_kmol_h':no,
     'NH3_recycled_kmol_h':mol('46',1),'Capture_AC_kW':cap,'NH3_recovery_AC_kW':rec,
     'Electric_heating_kW':sum(other_heat.values())+thermal_heater,'SOFC_thermal_heater_kW':thermal_heater,'Cooling_pump_AC_kW':cool_pump,
     'Heat_rejection_kW':cool_base+cool_pump+chiller_ac,'Chiller_AC_kW':chiller_ac,'Chiller_COP_assumption':cop,'Chiller_evaporator_load_kW':cold_load,'Warm_water_flow_kg_h':(warm_base+warm_pump)*1000/(4180*5)*3600,'Cold_glycol_flow_kg_h':cold_load*1000/(3600*5)*3600,'allocated_energy_residual_kW':energy_residual,
     'ORC_condensation_C_CoolProp':PropsSI('T','P',s['22']['PRES_OUT']*1e5,'Q',0,'R245fa')-273.15,
     'cracker_NH3_conversion':1-mol('03',1)/mol('02',1),
     'external_water_kg_h':s['39']['MASSFLMX'],'liquid_water_out_kg_h':sum(mol(n,5)*18.01528 for n in ['36','49']),
     'outlet_NO_kmol_h':mol('51',7),'outlet_NO2_kmol_h':mol('51',8),
     'N2O_modeled':True,'outlet_N2O_kmol_h':mol('51',9),'outlet_NH3_kmol_h':mol('51',1),'outlet_H2_kmol_h':mol('51',2),'R245fa_leakage_modeled':False}
    result={'utility_interfaces':utility_checks,'utility_assumptions':{'water_in_C':20,'water_out_C':25,'glycol_in_C':0,'glycol_out_C':5,'glycol_cp_J_kgK':3600,'glycol_density_kg_m3':1030,'refrigerant_evap_C':-20,'refrigerant_cond_C':45,'COP_second_law_fraction':.45,'water_source':'external once-through 20 C water; no implicit production of chilled 20 C water'},'summary':summary,'checks':checks,'temperature_profiles':profiles,'ORC_EOS_comparison':cp_orc,
     'heat_partition_kW':{'SOFC':stack_reject,'ICE':ice_reject,'NORR':norr_reject,'other_heating':other_heat,'other_cooling':other_cool},
     'experimental_validation':{'SOFC':'graph screening only; air flow and pore size not confirmed',
     'ICE':'not validated for wet SOFC offgas; fixed efficiency remains an assumption',
     'cracker':'fixed conversion, catalyst kinetics and amount not established',
     'NORR':'single source MEA operating point; capture/recovery remain ideal separators',
     'ORC':'EOS and heat-balance crosscheck; no hardware performance validation'},
     'released_for_training':False}
    assert all(checks.values()), str(checks)
    return result
