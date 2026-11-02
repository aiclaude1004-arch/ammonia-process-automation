"""Experimental voltage correlation, not a mechanistic polarization model.
Barelli, Bidini, Cinti (2020), DOI 10.3390/en13236173, Eq.11.
All public interfaces state units; no extrapolation outside measured T/Uf/J/X.
"""
import math

F = 96485.33212  # C/mol

def voltage(temperature_C, utilization, current_density_A_m2, external_cracking):
    if abs(temperature_C - 750.0) > 1e-8:
        raise ValueError('Experimental correlation supports 750 C only')
    if not 0.6 <= utilization <= 0.8:
        raise ValueError('Uf outside 0.6--0.8')
    if not 2000 <= current_density_A_m2 <= 5000:
        raise ValueError('J outside 200--500 mA/cm2')
    if not 0 <= external_cracking <= 1:
        raise ValueError('External NH3 cracking fraction outside 0--1')
    j_mA_cm2 = current_density_A_m2 / 10.0
    return (1.0342 - 0.1686 * utilization - 2.3638e-4 * j_mA_cm2
            - 3.2182e-5 * external_cracking)

def stack(h2_kmol_h, nh3_kmol_h, n2_kmol_h, h2o_kmol_h,
          utilization, total_active_area_m2, temperature_C=750.,
          oxygen_utilization=0.2, inverter_efficiency=0.95):
    """Total area = number of cells * individual cell area.
    Returned equivalent current is sum of cell currents, NOT terminal current.
    Complete residual NH3 cracking follows the paper's SYSTEM assumption.
    This does not assert experimentally zero ammonia slip.
    """
    values=[h2_kmol_h, nh3_kmol_h, n2_kmol_h, h2o_kmol_h]
    if not all(math.isfinite(x) and x >= 0 for x in values):
        raise ValueError('Negative or nonfinite material input')
    if total_active_area_m2 <= 0 or not 0 < oxygen_utilization <= 1:
        raise ValueError('Invalid equipment area or oxygen utilization')
    if not 0 < inverter_efficiency <= 1:
        raise ValueError('Invalid inverter efficiency')
    potential_h2 = h2_kmol_h + 1.5 * nh3_kmol_h
    if potential_h2 <= 0:
        raise ValueError('No available fuel')
    if h2o_kmol_h > 1e-9 or abs(n2_kmol_h - h2_kmol_h / 3) > 1e-6:
        raise ValueError('Feed differs from tested dry NH3/H2/N2 cracking mixture')
    consumed = potential_h2 * utilization
    equivalent_current = consumed * 1000 / 3600 * 2 * F
    j = equivalent_current / total_active_area_m2
    x = h2_kmol_h / potential_h2
    v = voltage(temperature_C, utilization, j, x)
    oxygen_consumed = consumed / 2
    oxygen_feed = oxygen_consumed / oxygen_utilization
    out={'H2':potential_h2-consumed,'NH3':0.,
         'N2':n2_kmol_h+nh3_kmol_h/2,'H2O':h2o_kmol_h+consumed}
    dc=equivalent_current*v/1000
    return {'model':'Barelli2020_Eq11_experimental_correlation',
            'temperature_C':temperature_C,'Uf':utilization,'X_external':x,
            'current_density_A_m2':j,'cell_voltage_V':v,
            'total_active_area_m2':total_active_area_m2,
            'sum_cell_currents_A':equivalent_current,
            'SOFC_DC_kW':dc,'SOFC_AC_kW':dc*inverter_efficiency,
            'inverter_loss_kW':dc*(1-inverter_efficiency),
            'H2_consumed_kmol_h':consumed,'O2_consumed_kmol_h':oxygen_consumed,
            'air_O2_kmol_h':oxygen_feed,'air_N2_kmol_h':oxygen_feed*79/21,
            'cathode_out_O2_kmol_h':oxygen_feed-oxygen_consumed,
            'anode_out_kmol_h':out,
            'oxygen_utilization_matches_experiment':abs(oxygen_utilization-.2)<1e-9,
            'pressure_validation':'No pressure dependence fitted; pressure extrapolation unvalidated',
            'ammonia_slip_model':'complete cracking assumption; measured slip is not zero',
            'experimental_validation_of_our_plant':False}

def heat_balance(inlet_enthalpy_kW, outlet_enthalpy_kW, dc_kW, heat_loss_kW=0.):
    """H_in + Q_external = H_out + P_DC + Q_loss + Q_export.
    Export and external demand are not both assigned to the same residual.
    Does not assert feasible heat exchange temperature.
    """
    available=inlet_enthalpy_kW-outlet_enthalpy_kW-dc_kW-heat_loss_kW
    return {'heat_export_kW':max(available,0.),
            'external_heat_required_kW':max(-available,0.),
            'energy_residual_kW':inlet_enthalpy_kW+max(-available,0.)
                -outlet_enthalpy_kW-dc_kW-heat_loss_kW-max(available,0.)}
