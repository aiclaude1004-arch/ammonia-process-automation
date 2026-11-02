"""Steady 0D electrochemistry with through-electrode multicomponent DGM.

Nemati et al. 2024, DOI 10.1016/j.enconman.2024.118396, Tables 1,5,6.
This is a reduced implementation, NOT a reproduction of the paper's 3D solver.
Ideal gases; isothermal mean channels; no Darcy convection in porous electrodes.
NASA7 thermodynamics from official Cantera gri30.yaml; no GRI kinetics used.
Positive current denotes fuel-cell operation. All internals SI.
"""
import math, re, json
from pathlib import Path
F=96485.33212
R=8.31446261815324
ROOT=Path(__file__).resolve().parents[1]
DATA=(ROOT/'01_Literature/gri30.yaml').read_text(encoding='utf-8')
PAR={'gamma_an':9.996e6,'gamma_ca':2.531e8,'Ea_an':120800.,'Ea_ca':149500.,
     'alpha_an':.616,'alpha_ca':.9,'a':-.225,'b':.5,'m':.138,
     'kdiff_an':.034,'kdiff_ca':.199,'Bohm':7.825e11,'Ea_ohm':80020.,
     'anode_m':.000310,'cathode_m':.000070,
     'pore_diameter_m':1e-6} # Pore diameter is a declared assumption, not Table 6.
MW={'H2':2.01588,'H2O':18.01528,'N2':28.0134,'NH3':17.03052,'O2':31.9988}
FV={'H2':7.07,'H2O':12.7,'N2':17.9,'NH3':20.7,'O2':16.6}

def thermo(sp,T):
    """Return h [J/mol], s [J/mol/K], g [J/mol]; NASA standard pressure 1 atm."""
    sec=DATA.split('- name: '+sp+'\n',1)[1].split('\n- name:',1)[0]
    ranges=[float(x) for x in re.search(r'temperature-ranges: \[([^]]+)\]',sec)[1].split(',')]
    if not ranges[0]<=T<=ranges[-1]:raise ValueError('NASA temperature range')
    coeff=re.findall(r'- \[([^]]+)\]',sec.split('    data:',1)[1].split('  transport:')[0],re.S)
    a=[float(x) for x in coeff[int(T>ranges[1])].split(',')]
    h=R*T*(a[0]+a[1]*T/2+a[2]*T*T/3+a[3]*T**3/4+a[4]*T**4/5+a[5]/T)
    s=R*(a[0]*math.log(T)+a[1]*T+a[2]*T*T/2+a[3]*T**3/3+a[4]*T**4/4+a[6])
    return h,s,h-T*s

def bisect(fn,lo,hi,tol=1e-11):
    flo=fn(lo)
    if flo*fn(hi)>0:raise ValueError('Root not bracketed')
    for _ in range(90):
        mid=(lo+hi)/2;fm=fn(mid)
        if hi-lo<tol:return mid
        if flo*fm<=0:hi=mid
        else:lo=mid;flo=fm
    return (lo+hi)/2

def equilibrium_out(feed,consumed,T,p_bar):
    """NH3 <=> .5 N2 + 1.5 H2 at fixed H2 electrochemical consumption.
    Allows finite NH3 slip and reverse synthesis; excludes other N species.
    Feed and consumed use the same molar-flow unit (here kmol/h).
    """
    h2=feed.get('H2',0);nh=feed.get('NH3',0);n2=feed.get('N2',0);water=feed.get('H2O',0)
    dg=.5*thermo('N2',T)[2]+1.5*thermo('H2',T)[2]-thermo('NH3',T)[2]
    logK=-dg/R/T
    lo=max(-2*n2,(consumed-h2)/1.5)+1e-12;hi=nh-1e-12
    if hi<=lo:raise ValueError('Fuel starvation')
    def out(x):return {'NH3':nh-x,'H2':h2+1.5*x-consumed,'N2':n2+.5*x,'H2O':water+consumed}
    def residual(x):
        f=out(x);s=sum(f.values());p={k:v/s*p_bar/1.01325 for k,v in f.items()}
        return .5*math.log(p['N2'])+1.5*math.log(p['H2'])-math.log(p['NH3'])-logK
    x=bisect(residual,lo,hi)
    return out(x),x

def diffusion(i,j,T,p_Pa):
    """Fuller: cm2/s, pressure atm, MW g/mol -> m2/s."""
    mij=2/(1/MW[i]+1/MW[j])
    return .00143*T**1.75/((p_Pa/101325)*math.sqrt(mij)*(FV[i]**(1/3)+FV[j]**(1/3))**2)*1e-4

def tpb(bulk,T,flux,thickness,kdiff,steps=80):
    """Multicomponent DGM with zero Darcy contribution; partial pressures Pa.
    N_i/D_Ki + sum((y_j N_i-y_i N_j)/D_ij) = -d(p_i)/dx/(RT).
    Keeps inert flux zero; pressure variation is solved rather than normalized away.
    """
    names=list(bulk);p=[bulk[n] for n in names]
    dk={n:kdiff*PAR['pore_diameter_m']/3*math.sqrt(8*R*T/(math.pi*MW[n]/1000)) for n in names}
    def grad(z):
        if min(z)<0 or sum(z)<=0:raise ValueError('Transport limit: nonpositive partial pressure')
        total=sum(z);y=dict(zip(names,[v/total for v in z]));res=[]
        for i in names:
            term=flux.get(i,0)/dk[i]
            for j in names:
                if j!=i:term+=(y[j]*flux.get(i,0)-y[i]*flux.get(j,0))/(kdiff*diffusion(i,j,T,total))
            res.append(-R*T*term)
        return res
    dx=thickness/steps
    for _ in range(steps):
        k1=grad(p);k2=grad([v+dx*a/2 for v,a in zip(p,k1)])
        k3=grad([v+dx*a/2 for v,a in zip(p,k2)]);k4=grad([v+dx*a for v,a in zip(p,k3)])
        p=[v+dx*(a+2*b+2*c+d)/6 for v,a,b,c,d in zip(p,k1,k2,k3,k4)]
    if min(p)<=0:raise ValueError('Transport limit reached')
    return dict(zip(names,p))

def activation(j,j0,T,alpha):
    if j==0:return 0.
    if j<0 or j0<=0:raise ValueError('Invalid fuel-cell current')
    # Positive forward/reverse exponents must have opposite signs.
    fn=lambda eta:j0*(math.exp(alpha*2*F*eta/R/T)-math.exp(-(1-alpha)*2*F*eta/R/T))-j
    return bisect(fn,0.,2.)

def polarization(T,j,anode,ca,p_an_bar=1.1,p_ca_bar=1.1,steps=80):
    """Channel compositions must contain H2 and H2O >0; dry OCV is undefined."""
    if not 973.15<=T<=1123.15:raise ValueError('Selected HT study domain: 700--850 C')
    if not 0<=j<=10000:raise ValueError('Current domain 0--1 A/cm2')
    ap={k:v/sum(anode.values())*p_an_bar*1e5 for k,v in anode.items() if v>0}
    cp={k:v/sum(ca.values())*p_ca_bar*1e5 for k,v in ca.items() if v>0}
    if ap.get('H2O',0)<=0 or ap.get('H2',0)<=0:raise ValueError('Finite H2/H2O required')
    at=tpb(ap,T,{'H2':j/(2*F),'H2O':-j/(2*F)},PAR['anode_m'],PAR['kdiff_an'],steps)
    ct=tpb(cp,T,{'O2':j/(4*F)},PAR['cathode_m'],PAR['kdiff_ca'],steps)
    dg=thermo('H2O',T)[2]-thermo('H2',T)[2]-.5*thermo('O2',T)[2]
    e0=-dg/(2*F)
    en=e0+R*T/(2*F)*math.log(ap['H2']/ap['H2O']*math.sqrt(cp['O2']/101325))
    conc_an=R*T/(2*F)*math.log(ap['H2']/at['H2']*at['H2O']/ap['H2O'])
    conc_ca=R*T/(4*F)*math.log(cp['O2']/ct['O2'])
    # gamma0 is A/(m2 K), so gamma=gamma0*T. Reference pressure 1 bar per model.
    ja=PAR['gamma_an']*T*(at['H2']/1e5)**PAR['a']*(at['H2O']/1e5)**PAR['b']*math.exp(-PAR['Ea_an']/R/T)
    jc=PAR['gamma_ca']*T*(ct['O2']/1e5)**PAR['m']*math.exp(-PAR['Ea_ca']/R/T)
    act_a=activation(j,ja,T,PAR['alpha_an']);act_c=activation(j,jc,T,PAR['alpha_ca'])
    asr=T/PAR['Bohm']*math.exp(PAR['Ea_ohm']/R/T);ohm=j*asr
    v=en-act_a-act_c-conc_an-conc_ca-ohm
    if v<=0:raise ValueError('No positive fuel-cell voltage')
    return {'cell_voltage_V':v,'standard_voltage_V':e0,'Nernst_V':en,
            'activation_anode_V':act_a,'activation_cathode_V':act_c,
            'concentration_anode_V':conc_an,'concentration_cathode_V':conc_ca,
            'ohmic_V':ohm,'ASR_ohmic_ohm_m2':asr,'j0_anode_A_m2':ja,'j0_cathode_A_m2':jc,
            'anode_TPB_Pa':at,'cathode_TPB_Pa':ct}

def stack(feed,utilization=.7,area_m2=1608.0888470646728,temperature_C=750,
          pressure_bar=1.1,oxygen_utilization=.2,inverter_efficiency=.95):
    if not all(math.isfinite(v) and v>=0 for v in feed.values()):raise ValueError('Invalid feed')
    if not 0<utilization<1 or not 0<oxygen_utilization<1 or area_m2<=0:raise ValueError('Invalid specification')
    T=temperature_C+273.15;potential=feed.get('H2',0)+1.5*feed.get('NH3',0)
    consumed=potential*utilization;current=consumed*1000/3600*2*F;j=current/area_m2
    inlet,_=equilibrium_out(feed,0,T,pressure_bar)
    outlet,extent=equilibrium_out(feed,consumed,T,pressure_bar)
    mean={n:(inlet[n]+outlet[n])/2 for n in inlet}
    o2=consumed/2/oxygen_utilization;n2=o2*79/21
    pol=polarization(T,j,mean,{'O2':o2-consumed/4,'N2':n2},pressure_bar,pressure_bar)
    dc=current*pol['cell_voltage_V']/1000
    return {**pol,'model':'Nemati2024_based_reduced_mechanistic_DGM',
            'temperature_C':temperature_C,'Uf':utilization,'current_density_A_m2':j,
            'total_active_area_m2':area_m2,'sum_cell_currents_A':current,
            'SOFC_DC_kW':dc,'SOFC_AC_kW':dc*inverter_efficiency,
            'inverter_loss_kW':dc*(1-inverter_efficiency),
            'H2_consumed_kmol_h':consumed,'O2_consumed_kmol_h':consumed/2,
            'air_O2_kmol_h':o2,'air_N2_kmol_h':n2,'anode_out_kmol_h':outlet,
            'NH3_decomposed_kmol_h':extent,'NH3_conversion':extent/feed['NH3'] if feed.get('NH3',0)>0 else None,
            'independent_experimental_validation':False,'release_for_training':False}

if __name__=='__main__':
    result=stack({'H2':148.095,'NH3':1.27,'N2':49.365,'H2O':0.})
    (ROOT/'04_Validation/Mechanistic_Baseline.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
