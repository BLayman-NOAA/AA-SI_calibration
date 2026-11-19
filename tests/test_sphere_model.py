# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for the theoretical target strength of a calibration sphere."""

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from aa_si_calibration.sphere_model import sphere_ka, sphere_target_strength

FREQUENCIES = [18000.0, 38000.0, 70000.0, 120000.0, 200000.0, 333000.0]


def test_matches_ices_crr_326_table_3_2():
    """38.1 mm tungsten carbide at the report's nominal 10 C, 35 psu, 30 m."""
    expected = [-42.70, -42.39, -41.29, -39.48, -39.23, -36.73]

    computed = sphere_target_strength(FREQUENCIES, 38.1, 1490.0)

    assert computed == pytest.approx(expected, abs=0.02)


def test_matches_ices_crr_326_table_2_3():
    """The same sphere at 1500 m s-1, given to 0.1 dB."""
    computed = sphere_target_strength([38000.0, 70000.0, 120000.0, 200000.0], 38.1, 1500.0)

    assert computed == pytest.approx([-42.4, -41.4, -39.5, -39.1], abs=0.06)


def _numbers(text):
    return np.array([float(x) for x in text.split(";") if x.strip()])


@pytest.mark.parametrize("name", [
    "CalibrationDataFile-D20230720-T184613_200FM_1ms_full.xml",
    "CalibrationDataFile-D20230721-T000056-200fm-22mm.xml",
])
def test_matches_the_curve_the_ek80_software_stored(request, name):
    """Away from the nulls, where a tiny shift in a null moves the value a lot."""
    path = request.config.rootpath / "notebooks/example_data/ek80_FM_cal_file_input_folder" / name
    root = ET.parse(path).getroot()
    target = root.find(".//TargetReference")
    frequency = _numbers(target.findtext("Frequency"))
    stored = _numbers(target.findtext("Response"))
    computed = sphere_target_strength(
        frequency, float(target.findtext("Diameter")), float(root.findtext(".//SoundVelocity")),
    )

    smooth = np.abs(np.gradient(stored, frequency / 1000.0)) < 1.0
    assert smooth.sum() > 0.7 * frequency.size
    assert np.abs(computed - stored)[smooth].mean() < 0.03
    assert np.abs(computed - stored)[smooth].max() < 0.15


def test_copper_spheres_have_their_usual_values():
    """23 mm copper is a standard 120 kHz sphere, 13.7 mm a 200 kHz one."""
    assert sphere_target_strength(120000.0, 23.0, 1490.0, "copper")[0] == pytest.approx(
        -40.4, abs=0.2
    )
    assert sphere_target_strength(200000.0, 13.7, 1490.0, "copper")[0] == pytest.approx(
        -45.0, abs=0.2
    )


def test_ka():
    assert sphere_ka(333000.0, 38.1, 1490.0) == pytest.approx(26.75, abs=0.01)


def test_an_unknown_material_is_refused():
    with pytest.raises(ValueError, match="Unknown sphere material 'brass'"):
        sphere_target_strength(38000.0, 38.1, 1490.0, "brass")


def test_a_wide_band_in_one_call_stays_finite():
    computed = sphere_target_strength(np.linspace(10000.0, 450000.0, 500), 38.1, 1490.0)

    assert np.all(np.isfinite(computed))
    assert -80.0 < computed.min() and computed.max() < -30.0


def test_a_low_frequency_is_not_spoiled_by_a_high_one_in_the_same_call():
    together = sphere_target_strength([18000.0, 2000000.0], 38.1, 1490.0)
    alone = sphere_target_strength([18000.0], 38.1, 1490.0)

    assert np.all(np.isfinite(together))
    assert together[0] == pytest.approx(alone[0], abs=1e-9)
