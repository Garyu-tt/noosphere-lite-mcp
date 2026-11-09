#!/usr/bin/env python3
"""Toy constraints for cross-problem hypotheses; no full physics fit."""
import json
import math
from pathlib import Path

R = 0.120 / 0.0224
m_p = 0.9382720813  # GeV
Y_B_obs = 6.120e-10 / 7.04
c_sph = 28 / 79
kappa = 0.1  # illustrative, not measured
m_nu = 0.05e-9  # GeV
v = 174.0  # GeV
g_star = 106.75

epsilon_per_M_GeV = (3 / (16 * math.pi)) * m_nu / (v * v)
M1_min = Y_B_obs * g_star / (c_sph * kappa * epsilon_per_M_GeV)
Y_B_max_at_TeV = c_sph * kappa * epsilon_per_M_GeV * 1000 / g_star

result = {
    "mchi_GeV_if_r_equals_f_equals_1": R * m_p,
    "mchi_GeV_if_dark_asym_equals_primordial_B_minus_L": R * m_p * c_sph,
    "observed_YB": Y_B_obs,
    "hierarchical_M1_min_GeV": M1_min,
    "hierarchical_YB_max_at_TeV": Y_B_max_at_TeV,
    "hierarchical_TeV_underproduction_factor": Y_B_obs / Y_B_max_at_TeV,
    "near_resonant_efficiency_needed_if_epsilon_reaches_1over200":
       Y_B_obs * g_star / (c_sph / 200),
    "simple_H0_ratio_for_delta_magnitude_0_0646":
       10 ** (0.0646 / 5),
}
assert 5.02 < result["mchi_GeV_if_r_equals_f_equals_1"] < 5.04
assert 1.77 < result["mchi_GeV_if_dark_asym_equals_primordial_B_minus_L"] < 1.79
assert 2.6e9 < M1_min < 2.7e9
print(json.dumps(result, indent=2))
