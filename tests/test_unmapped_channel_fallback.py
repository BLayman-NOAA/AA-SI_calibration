# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""A channel with no calibration match falls back to the raw file's own values.

HB1603 transmitted 18 and 38 kHz at 2000 W on leg 1 and 1000 W afterwards,
while the only calibration was measured at 1000 W. transmit_power is matched
exactly, so leg 1's two channels match nothing at all.
"""

from __future__ import annotations

import types

import pytest

from aa_si_calibration import calibration as calibration_module

CH_18 = "GPT  18 kHz 009072056b0e 2-1 ES18-11"
CH_38 = "GPT  38 kHz 0090720346bc 1-1 ES38B"

STORED = {
    "cal_params": {
        "gain_correction": [20.0, 25.0],
        "sa_correction": [-0.1, -0.2],
        "equivalent_beam_angle": [-17.0, -20.7],
        "beamwidth_athwartship": [11.0, 6.9],
        "beamwidth_alongship": [10.5, 6.8],
        "angle_offset_athwartship": [0.01, 0.02],
        "angle_offset_alongship": [-0.07, -0.03],
        "angle_sensitivity_athwartship": [13.9, 21.9],
        "angle_sensitivity_alongship": [13.9, 21.9],
    },
    "env_params": {"sound_speed": 1500.0, "sound_absorption": [0.0018, 0.0095]},
    "other_params": {
        "frequency_nominal": [18000.0, 38000.0],
        "transmit_duration_nominal": [0.001024, 0.001024],
        "transmit_power": [2000.0, 2000.0],
        "transmit_bandwidth": [1570.0, 2430.0],
        "sample_interval": [0.000128, 0.000128],
    },
}

CAL_38 = {
    "gain_correction": [26.5],
    "sa_correction": [-0.65],
    "equivalent_beam_angle": -20.7,
    "beamwidth_transmit_major": [6.9],
    "beamwidth_transmit_minor": [6.8],
    "echoangle_major": [0.02],
    "echoangle_minor": [-0.03],
    "echoangle_major_sensitivity": [21.9],
    "echoangle_minor_sensitivity": [21.9],
    "absorption_indicative": 0.0095,
    "sound_speed_indicative": 1522.6,
    "frequency": [38000.0],
    "transmit_duration_nominal": 0.001024,
    "transmit_power": 1000.0,
    "transmit_bandwidth": 2430.0,
    "sample_interval": 0.000128,
    "source_filenames": ["HBB_038kHz_18July2016.cal"],
    "source_file_type": ".cal",
}


class _EchoData:
    """Just the one lookup extract_standardized_calibration_parameters makes."""

    def __init__(self, channels):
        beam = types.SimpleNamespace(channel=types.SimpleNamespace(values=channels))
        self._groups = {"Sonar/Beam_group1": beam}

    def __getitem__(self, key):
        return self._groups[key]


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the file read and capture what reaches the terminal."""
    printed = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: printed.append(" ".join(str(a) for a in args)),
    )
    monkeypatch.setattr(
        calibration_module, "extract_netcdf_calibration_parameters",
        lambda *_a, **_k: STORED,
    )
    return printed


def _extract(**kwargs):
    return calibration_module.extract_standardized_calibration_parameters(
        {"cal-38": CAL_38},
        {"a.raw": {CH_38: "cal-38"}},
        filename="a.raw",
        echodata=_EchoData([CH_18, CH_38]),
        **kwargs,
    )


def test_unmapped_channel_falls_back_to_the_files_own_values(stubbed):
    out = _extract()

    # Channel order follows the EchoData, so the fallback is first.
    assert out["cal_params"]["gain_correction"] == [20.0, 26.5]
    assert out["cal_params"]["sa_correction"] == [-0.1, -0.65]
    assert out["cal_params"]["equivalent_beam_angle"] == [-17.0, -20.7]
    assert out["other_params"]["transmit_power"] == [2000.0, 1000.0]
    assert out["other_params"]["unmapped_channels"] == [CH_18]


def test_the_fallback_says_so_on_the_terminal(stubbed):
    _extract()

    assert any(CH_18 in line for line in stubbed)
    assert any("no matching calibration" in line for line in stubbed)


def test_a_mapped_file_reports_no_unmapped_channels(stubbed):
    out = calibration_module.extract_standardized_calibration_parameters(
        {"cal-38": CAL_38},
        {"a.raw": {CH_38: "cal-38"}},
        filename="a.raw",
        echodata=_EchoData([CH_38]),
    )

    assert out["other_params"]["unmapped_channels"] == []
    assert stubbed == []


def test_error_mode_still_raises(stubbed):
    with pytest.raises(ValueError, match="18 kHz"):
        _extract(unmapped_channels="error")


def test_warn_without_echodata_raises(stubbed):
    """There is nothing to fall back to, so warn cannot quietly continue."""
    with pytest.raises(ValueError, match="18 kHz"):
        calibration_module.extract_standardized_calibration_parameters(
            {"cal-38": CAL_38},
            {"a.raw": {CH_18: None, CH_38: "cal-38"}},
            filename="a.raw",
        )


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unmapped_channels"):
        _extract(unmapped_channels="ignore")


def test_unmatched_channels_are_reported_on_the_terminal(monkeypatch):
    """The per-channel NO MATCH blocks go to the step log, which nobody reads."""
    from aa_si_calibration.mapping_algorithm import UnmatchedChannel

    printed = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: printed.append(" ".join(str(a) for a in args)),
    )
    result = types.SimpleNamespace(
        unmatched_channels=[
            UnmatchedChannel("a.raw", CH_18),
            UnmatchedChannel("b.raw", CH_18),
        ]
    )

    calibration_module._warn_unmatched_channels(result)

    assert any("1 channel(s) matched no calibration" in line for line in printed)
    assert any(CH_18 in line and "2 raw file(s)" in line for line in printed)


def test_a_complete_mapping_says_nothing(monkeypatch):
    printed = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: printed.append(args),
    )

    calibration_module._warn_unmatched_channels(
        types.SimpleNamespace(unmatched_channels=[])
    )

    assert printed == []


def test_a_widened_tolerance_is_reported_once(monkeypatch):
    """Widening a tolerance is a scientific decision, so it has to be visible."""
    printed = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: printed.append(" ".join(str(a) for a in args)),
    )

    merged = calibration_module._merged_tolerances({"transmit_power": 1000.0})

    assert merged["transmit_power"] == 1000.0
    # Everything else keeps its default, or transmit_duration_nominal's 1e-6
    # would drop to 0 and no channel would match at all.
    assert merged["transmit_duration_nominal"] == 1e-6
    assert merged["frequency"] == 1.0
    assert sum("tolerance overridden" in line for line in printed) == 1
    assert any("transmit_power: 1 -> 1000" in line for line in printed)


def test_the_defaults_alone_say_nothing(monkeypatch):
    printed = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: printed.append(args),
    )

    assert calibration_module._merged_tolerances(None) == (
        calibration_module.DEFAULT_TOLERANCES
    )
    assert calibration_module._merged_tolerances({"transmit_power": 1.0}) == (
        calibration_module.DEFAULT_TOLERANCES
    )
    assert printed == []


def test_the_widened_tolerance_matches_a_2000w_channel():
    """The whole point: 2000 W data against a 1000 W calibration."""
    from aa_si_calibration.mapping_algorithm import values_match_with_tolerance

    default = calibration_module._merged_tolerances(None)
    widened = calibration_module._merged_tolerances({"transmit_power": 1000.0})

    assert not values_match_with_tolerance(2000.0, 1000.0, "transmit_power", default)
    assert values_match_with_tolerance(2000.0, 1000.0, "transmit_power", widened)
