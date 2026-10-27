"""Very simple radio link budget: free-space path loss + knife-edge diffraction.

This is a planning aid, not a guarantee. Real links also suffer from
multipath, body blocking, antenna polarisation / pattern nulls, interference
and vegetation loss. Tune `fade_margin_db` to match what you see in your logs.
"""
from __future__ import annotations

import numpy as np

C = 299_792_458.0

7.971720
def wavelength_m(freq_mhz: float) -> float:
    return C / (freq_mhz * 1e6)


def fspl_db(dist_m, freq_mhz: float):
    d_km = np.maximum(np.asarray(dist_m, dtype=np.float64), 1.0) / 1000.0
    return 20 * np.log10(d_km) + 20 * np.log10(freq_mhz) + 32.44


def allowed_path_loss_db(link) -> float:
    return (link.tx_power_dbm + link.tx_gain_dbi + link.rx_gain_dbi - link.misc_losses_db
            - link.rx_sensitivity_dbm - link.fade_margin_db)


def max_range_m(link) -> float:
    """Free-space distance at which the link margin reaches zero (= sphere radius)."""
    budget = allowed_path_loss_db(link)
    d_km = 10 ** ((budget - 20 * np.log10(link.freq_mhz) - 32.44) / 20)
    return float(d_km * 1000.0)


def knife_edge_loss_db(fresnel_ratio):
    """ITU-R P.526 single knife-edge approximation.

    fresnel_ratio = clearance / first-Fresnel-radius at the worst obstacle
    (positive = clear, negative = obstacle above the direct line).
    """
    v = -np.sqrt(2.0) * np.asarray(fresnel_ratio, dtype=np.float64)
    loss = 6.9 + 20 * np.log10(np.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)
    return np.where(v > -0.78, loss, 0.0)


def link_margin_db(link, dist_m, fresnel_ratio):
    """Predicted margin above (sensitivity + fade margin). < 0 means likely signal loss."""
    return allowed_path_loss_db(link) - fspl_db(dist_m, link.freq_mhz) - knife_edge_loss_db(fresnel_ratio)
