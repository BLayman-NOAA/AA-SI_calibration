# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for the warnings about calibration records and their spheres."""

import json

import numpy as np

from aa_si_calibration import _console
from aa_si_calibration.calibration import standardize_calibration_files
from aa_si_calibration.calibration_checks import (
    combination_warnings,
    print_warnings,
    sphere_label,
    sphere_warnings,
)
from aa_si_calibration.sphere_model import sphere_target_strength


def _codes(warnings):
    return [w["code"] for w in warnings]


def test_a_large_sphere_is_flagged_at_a_high_frequency(calibration_record):
    """A 38.1 mm sphere at 333 kHz has ka near 27, well over the limit."""
    record = calibration_record(
        "k1", frequency=[333000.0], frequency_start=333000.0, frequency_end=333000.0,
    )

    (warning,) = [w for w in sphere_warnings("k1", record) if w["code"] == "sphere_size"]

    assert warning["severity"] == "caution"
    assert warning["calibration_key"] == "k1"
    assert warning["band_hz"] == [333000.0, 333000.0]
    assert warning["value"] == 26.75
    assert "38.1 mm sphere" in warning["message"]


def test_the_standard_sphere_is_quiet_at_its_usual_frequencies(calibration_record):
    for frequency in (18000.0, 38000.0, 70000.0, 120000.0, 200000.0):
        record = calibration_record(
            "k1", frequency=[frequency], frequency_start=frequency, frequency_end=frequency,
        )

        assert sphere_warnings("k1", record) == []


def test_the_sphere_size_warning_gives_the_range_affected(fm_calibration_record):
    """ka passes 16.5 for a 38.1 mm sphere a little above 205 kHz."""
    frequency = [160000.0 + 5000.0 * i for i in range(21)]
    record = fm_calibration_record(
        "k1", frequency, [26.0] * 21, frequency_start=160000.0, frequency_end=260000.0,
    )

    (warning,) = [w for w in sphere_warnings("k1", record) if w["code"] == "sphere_size"]

    assert warning["band_hz"] == [210000.0, 260000.0]


def test_standard_copper_spheres_are_quiet_at_their_frequencies(calibration_record):
    for diameter, frequency in (
        (64.0, 18000.0), (60.0, 38000.0), (32.1, 70000.0), (23.0, 120000.0), (13.7, 200000.0),
    ):
        record = calibration_record(
            "k1", sphere_diameter=diameter, sphere_material="copper",
            frequency=[frequency], frequency_start=frequency, frequency_end=frequency,
        )

        assert sphere_warnings("k1", record) == []


def test_a_steep_rise_far_from_any_null_is_not_flagged(fm_calibration_record):
    """Below ka of 1 the target strength climbs fast in dB per kHz without a null."""
    frequency = np.arange(1000.0, 12001.0, 500.0)
    record = fm_calibration_record(
        "k1", frequency, [20.0] * frequency.size,
        frequency_start=1000.0, frequency_end=12000.0,
    )

    assert sphere_warnings("k1", record) == []


def test_a_large_sphere_at_a_low_frequency_is_not_flagged(fm_calibration_record):
    """The check scales with frequency, so a 64 mm sphere is quiet at 14-22 kHz."""
    frequency = np.arange(14000.0, 22001.0, 250.0)
    record = fm_calibration_record(
        "k1", frequency, [20.0] * frequency.size, sphere_diameter=64.0,
        frequency_start=14000.0, frequency_end=22000.0,
    )

    assert sphere_warnings("k1", record) == []


def test_the_standard_sphere_sits_on_a_null_at_333_khz(calibration_record):
    """A 38.1 mm sphere has a null near 331 kHz, inside a 0.5% shift of 333 kHz."""
    record = calibration_record(
        "k1", frequency=[333000.0], frequency_start=333000.0, frequency_end=333000.0,
    )

    (warning,) = [w for w in sphere_warnings("k1", record) if w["code"] == "near_null"]

    assert warning["band_hz"] == [333000.0, 333000.0]
    assert warning["value"] > 1.0
    assert "0.5%" in warning["message"]


def test_a_sphere_at_a_null_is_flagged(calibration_record):
    """A 22 mm sphere at 200 kHz CW sits on the flank of a null (ICES CRR 326 Table 2.3)."""
    record = calibration_record(
        "k1", sphere_diameter=22.0, frequency=[200000.0],
        frequency_start=200000.0, frequency_end=200000.0,
    )

    (warning,) = sphere_warnings("k1", record)

    assert warning["code"] == "near_null"
    assert warning["severity"] == "caution"
    assert warning["band_hz"] == [200000.0, 200000.0]
    assert warning["value"] > 2.0


def test_the_bottom_of_a_null_is_caught(fm_calibration_record):
    """Where the target strength is lowest the slope either side is steepest."""
    frequency = np.arange(80000.0, 100001.0, 500.0)
    ts = sphere_target_strength(frequency, 38.1, 1490.0)
    bottom = float(frequency[np.argmin(ts)])
    record = fm_calibration_record(
        "k1", frequency, [26.0] * frequency.size,
        frequency_start=80000.0, frequency_end=100000.0,
    )

    nulls = [w for w in sphere_warnings("k1", record) if w["code"] == "near_null"]

    assert any(w["band_hz"][0] <= bottom <= w["band_hz"][1] for w in nulls)
    assert all(w["band_hz"][1] - w["band_hz"][0] < 10000.0 for w in nulls)


def test_flagged_runs_are_split_by_quiet_points(fm_calibration_record):
    """Two nulls in one record give two warnings, not one spanning both."""
    frequency = np.arange(80000.0, 130001.0, 500.0)
    record = fm_calibration_record(
        "k1", frequency, [26.0] * frequency.size,
        frequency_start=80000.0, frequency_end=130000.0,
    )

    nulls = [w for w in sphere_warnings("k1", record) if w["code"] == "near_null"]

    assert len(nulls) >= 2


def test_a_null_run_does_not_span_a_gap(fm_calibration_record):
    """Flagged points either side of a gap are two runs, not one across it."""
    ts_frequency = np.arange(80000.0, 100001.0, 100.0)
    bottom = float(ts_frequency[np.argmin(sphere_target_strength(ts_frequency, 38.1, 1490.0))])
    frequency = [f for f in np.arange(bottom - 1500.0, bottom + 1501.0, 500.0) if f != bottom]
    frequency = [f for f in frequency if abs(f - bottom) > 600.0]
    record = fm_calibration_record(
        "k1", frequency, [26.0] * len(frequency),
        frequency_start=80000.0, frequency_end=100000.0,
    )

    nulls = [w for w in sphere_warnings("k1", record) if w["code"] == "near_null"]

    assert len(nulls) == 2
    assert all(not (w["band_hz"][0] < bottom < w["band_hz"][1]) for w in nulls)


def test_a_hand_edited_record_does_not_break_the_checks(calibration_record):
    """The standardize reuse path reads files that may have been edited by hand."""
    for overrides in (
        {"frequency": 38000.0},
        {"sphere_diameter": "38.1"},
        {"sound_speed_indicative": [1490.0]},
        {"frequency": [38000.0, None, "x"]},
    ):
        sphere_warnings("k1", calibration_record("k1", **overrides))

    assert sphere_label(calibration_record("k1", sphere_diameter="38.1")) == "tungsten carbide"
    assert sphere_label({}) == "unknown sphere"


def test_an_unknown_material_skips_only_the_null_check(calibration_record):
    record = calibration_record(
        "k1", sphere_material="brass", frequency=[333000.0],
        frequency_start=333000.0, frequency_end=333000.0,
    )

    assert _codes(sphere_warnings("k1", record)) == ["sphere_size"]


def test_an_unknown_sphere_or_sound_speed_is_not_judged(calibration_record):
    high = dict(frequency=[333000.0], frequency_start=333000.0, frequency_end=333000.0)

    assert sphere_warnings("k1", calibration_record("k1", sphere_diameter=None, **high)) == []
    assert sphere_warnings(
        "k1", calibration_record("k1", sound_speed_indicative=None, **high)
    ) == []
    assert sphere_warnings("k1", {}) == []


def test_each_gap_in_an_fm_record_is_noted(fm_calibration_record):
    """Points over 30-32 and 40-43 kHz of a 30-45 kHz band."""
    frequency = [30000.0 + 500.0 * i for i in range(5)] + [40000.0 + 500.0 * i for i in range(7)]
    record = fm_calibration_record("k1", frequency, [20.0] * len(frequency))

    warnings = sphere_warnings("k1", record)

    assert _codes(warnings) == ["coverage_gap", "coverage_gap"]
    assert [w["band_hz"] for w in warnings] == [[32000.0, 40000.0], [43000.0, 45000.0]]
    assert all(w["severity"] == "info" for w in warnings)


def test_a_small_overlap_difference_is_not_flagged(calibration_record):
    sources = {
        "k1": calibration_record("k1"),
        "k2": calibration_record("k2", gain_correction=[25.5]),
    }

    assert combination_warnings("avg", "average", sources) == []


def test_a_large_overlap_difference_is_flagged_with_its_size(calibration_record):
    sources = {
        "k1": calibration_record("k1"),
        "k2": calibration_record("k2", gain_correction=[25.6]),
    }

    (warning,) = combination_warnings("avg", "average", sources)

    assert warning["code"] == "overlap_difference"
    assert warning["severity"] == "caution"
    assert warning["value"] == 0.6
    assert "0.60 dB" in warning["message"]


def test_different_spheres_are_noted_on_an_average_only(calibration_record):
    sources = {
        "k1": calibration_record("k1"),
        "k2": calibration_record("k2", sphere_diameter=25.0),
    }

    (warning,) = combination_warnings("avg", "average", sources)

    assert warning["code"] == "different_spheres"
    assert warning["severity"] == "info"
    assert "38.1 mm tungsten carbide; 25 mm tungsten carbide" in warning["message"]


def test_warnings_are_json_safe(fm_calibration_record):
    frequency = [160000.0 + 5000.0 * i for i in range(21) if i not in (9, 10)]
    record = fm_calibration_record(
        "k1", frequency, [26.0] * len(frequency),
        frequency_start=160000.0, frequency_end=260000.0,
    )

    warnings = sphere_warnings("k1", record)

    assert {"sphere_size", "near_null", "coverage_gap"} <= set(_codes(warnings))
    assert json.loads(json.dumps(warnings)) == warnings


def test_cautions_go_to_the_terminal_and_notes_to_the_log(monkeypatch, capsys):
    shown = []
    monkeypatch.setattr(_console, "console_print", shown.append)

    print_warnings([
        {"severity": "caution", "message": "look at this"},
        {"severity": "info", "message": "for the record"},
    ])

    assert shown == ["WARNING: look at this"]
    assert capsys.readouterr().out == "NOTE: for the record\n"


def test_standardizing_returns_warnings_about_each_file(tmp_path, request):
    """The EK80 FM examples: a 38.1 mm sphere used up to 260 kHz, and its gaps.

    EK80 kept points on the flanks of the sphere's resonances near 214, 224
    and 250-258 kHz, so those are flagged as near a null.
    """
    cal_dir = request.config.rootpath / "notebooks/example_data/ek80_FM_cal_file_input_folder"

    out = standardize_calibration_files(
        cal_dir, tmp_path, frequencies=[], cruise_id="TEST", record_author="Tester",
        verbose=False,
    )

    large = [w for w in out["warnings"] if w["calibration_key"] == "2023-07-20__200000__config-2"]
    assert _codes(large) == ["sphere_size"] + ["near_null"] * 4 + ["coverage_gap"] * 3
    assert large[0]["band_hz"] == [214054.0, 260000.0]
    assert [w["band_hz"] for w in large[1:5]] == [
        [214054.0, 215055.0], [222062.0, 226066.0], [250090.0, 251091.0], [254094.0, 258098.0],
    ]
    assert [w["band_hz"] for w in large[5:]] == [
        [162002.0, 180020.0], [204044.0, 214054.0], [239079.0, 250090.0],
    ]
    json.dumps(out["warnings"])

    again = standardize_calibration_files(
        cal_dir, tmp_path, frequencies=[], cruise_id="TEST", record_author="Tester",
        verbose=False,
    )
    assert again["skipped"] is True
    assert sorted(again["warnings"], key=json.dumps) == sorted(out["warnings"], key=json.dumps)
