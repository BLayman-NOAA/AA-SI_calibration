# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Frequency-dependent calibrations reach echopype in the form it interpolates.

echopype takes a per-frequency calibration parameter as a DataArray with dims
(cal_channel_id, cal_frequency) covering exactly the channels of the beam group
it calibrates, and evaluates it at each ping's transmit centre frequency.
"""

import numpy as np
import pytest
import xarray as xr

from aa_si_calibration import calibration as calibration_module

CH_38 = "WBT 400528-15 ES38-7_ES"
CH_200 = "WBT 400509-15 ES200-7C_ES"
CH_18 = "WBT 400479-15 ES18_ES"


class _EchoData:
    """Beam groups as datasets with a channel coordinate and a transmit band."""

    def __init__(self, groups):
        self._groups = {
            name: xr.Dataset(
                {
                    "transmit_frequency_start": (("channel", "ping_time"), [[b[0]] for b in bands]),
                    "transmit_frequency_stop": (("channel", "ping_time"), [[b[1]] for b in bands]),
                },
                coords={"channel": list(channels), "ping_time": [0]},
            )
            for name, (channels, bands) in groups.items()
        }

    def __getitem__(self, key):
        return self._groups[key]


@pytest.fixture
def printed(monkeypatch):
    lines = []
    monkeypatch.setattr(
        calibration_module._console, "console_print",
        lambda *args, **_kw: lines.append(" ".join(str(a) for a in args)),
    )
    return lines


@pytest.fixture
def records(calibration_record, fm_calibration_record):
    """A 38 kHz FM calibration, a 200 kHz one with a gap at 210 kHz, and an 18 kHz CW one."""
    fm_38 = fm_calibration_record(
        "fm-38", [34000.0, 38000.0, 45000.0], [24.0, 25.0, 26.0],
        frequency_start=34000.0, frequency_end=45000.0,
        beamwidth_transmit_major=[7.5, 7.0, 6.5],
    )
    fm_200 = fm_calibration_record(
        "fm-200", [160000.0, 200000.0, 215000.0, 260000.0], [26.0, 27.0, 27.5, 28.0],
        frequency_start=160000.0, frequency_end=260000.0, nominal_transducer_frequency=200000.0,
        valid_frequency_bands=[[150000.0, 205000.0], [214000.0, 261000.0]],
    )
    cw_18 = calibration_record(
        "cw-18", gain_correction=[22.0], frequency=[18000.0], equivalent_beam_angle=-17.0,
    )
    return {"fm-38": fm_38, "fm-200": fm_200, "cw-18": cw_18}


MAPPING = {"a.raw": {CH_38: "fm-38", CH_200: "fm-200", CH_18: "cw-18"}}


def _extract(records, echodata, **kwargs):
    return calibration_module.extract_standardized_calibration_parameters(
        records, MAPPING, filename="a.raw", echodata=echodata, **kwargs,
    )


def test_fm_parameters_become_frequency_curves(records, printed):
    echodata = _EchoData({
        "Sonar/Beam_group1": ([CH_38, CH_18], [(34000.0, 45000.0), (18000.0, 18000.0)]),
    })

    out = _extract(records, echodata)

    gain = out["cal_params"]["gain_correction"]
    assert gain.dims == ("cal_channel_id", "cal_frequency")
    assert list(gain["cal_channel_id"].values) == [CH_38, CH_18]
    assert list(gain["cal_frequency"].values) == [34000.0, 38000.0, 45000.0]
    assert gain.sel(cal_channel_id=CH_38).values.tolist() == [24.0, 25.0, 26.0]
    assert gain.sel(cal_channel_id=CH_18).values.tolist() == [22.0, 22.0, 22.0]
    beamwidth = out["cal_params"]["beamwidth_athwartship"]
    assert beamwidth.sel(cal_channel_id=CH_38).values.tolist() == [7.5, 7.0, 6.5]
    beam_angle = out["cal_params"]["equivalent_beam_angle"]
    assert beam_angle.sel(cal_channel_id=CH_18).values.tolist() == [-17.0] * 3
    assert out["other_params"]["frequency_nominal"] == [38000.0, 18000.0]
    assert printed == []


def test_a_row_is_nan_outside_its_own_span(records, printed):
    echodata = _EchoData({
        "Sonar/Beam_group1": (
            [CH_38, CH_200], [(34000.0, 45000.0), (160000.0, 260000.0)],
        ),
    })

    gain = _extract(records, echodata)["cal_params"]["gain_correction"]

    row_38 = gain.sel(cal_channel_id=CH_38)
    assert np.isnan(row_38.sel(cal_frequency=160000.0))
    assert np.isfinite(row_38.sel(cal_frequency=38000.0))
    row_200 = gain.sel(cal_channel_id=CH_200)
    assert np.isnan(row_200.sel(cal_frequency=45000.0))


def test_the_waveform_mode_selects_the_beam_group(monkeypatch, records, printed):
    """A mixed file's CW channel is not in the broadband group echopype calibrates."""
    echodata = _EchoData({
        "Sonar/Beam_group1": ([CH_38, CH_18], [(34000.0, 45000.0), (18000.0, 18000.0)]),
        "Sonar/Beam_group2": ([CH_38], [(34000.0, 45000.0)]),
    })
    modes = []

    def beam_group(_echodata, waveform_mode, encode_mode):
        modes.append((waveform_mode, encode_mode))
        return "Sonar/Beam_group2"

    monkeypatch.setattr(calibration_module, "_beam_group", beam_group)

    out = _extract(records, echodata, waveform_mode="BB", encode_mode="complex")

    assert modes == [("BB", "complex")]
    assert out["other_params"]["channel"] == [CH_38]
    assert list(out["cal_params"]["gain_correction"]["cal_channel_id"].values) == [CH_38]


def test_a_nominal_beam_angle_is_carried_across_the_band(records, printed):
    """As echopype carries its own: EBA + 20 log10(nominal / f)."""
    echodata = _EchoData({"Sonar/Beam_group1": ([CH_200], [(160000.0, 240000.0)])})

    out = _extract(records, echodata)

    beam_angle = out["cal_params"]["equivalent_beam_angle"].sel(cal_channel_id=CH_200)
    expected = -20.7 + 20 * np.log10(200000.0 / beam_angle["cal_frequency"].values)
    assert np.allclose(beam_angle.values, expected)
    assert beam_angle.sel(cal_frequency=200000.0) == pytest.approx(-20.7)


def test_a_nominal_beam_width_and_sensitivity_are_carried_too(records, printed):
    records["fm-200"]["beamwidth_transmit_major"] = [7.0]
    records["fm-200"]["echoangle_major_sensitivity"] = [23.0]
    echodata = _EchoData({"Sonar/Beam_group1": ([CH_200], [(160000.0, 240000.0)])})

    out = _extract(records, echodata)

    beamwidth = out["cal_params"]["beamwidth_athwartship"].sel(cal_channel_id=CH_200)
    sensitivity = out["cal_params"]["angle_sensitivity_athwartship"].sel(cal_channel_id=CH_200)
    assert beamwidth.sel(cal_frequency=160000.0) == pytest.approx(7.0 * 200000.0 / 160000.0)
    assert sensitivity.sel(cal_frequency=160000.0) == pytest.approx(23.0 * 160000.0 / 200000.0)


def test_one_mode_without_the_other_is_refused(records):
    echodata = _EchoData({"Sonar/Beam_group1": ([CH_38], [(34000.0, 45000.0)])})

    with pytest.raises(ValueError, match="give both or neither"):
        _extract(records, echodata, waveform_mode="BB")


def test_a_waveform_mode_needs_echodata(records):
    with pytest.raises(ValueError, match="needs echodata"):
        calibration_module.extract_standardized_calibration_parameters(
            records, MAPPING, filename="a.raw", waveform_mode="BB", encode_mode="complex",
        )


def test_a_broadband_channel_has_no_fallback(monkeypatch, records, printed):
    echodata = _EchoData({"Sonar/Beam_group1": (["unmapped"], [(34000.0, 45000.0)])})
    monkeypatch.setattr(calibration_module, "_beam_group", lambda *_a: "Sonar/Beam_group1")

    with pytest.raises(ValueError, match="CW only"):
        _extract(records, echodata, waveform_mode="BB", encode_mode="complex")


def test_a_centre_frequency_in_a_calibration_gap_is_reported(records, printed):
    echodata = _EchoData({"Sonar/Beam_group1": ([CH_200], [(160000.0, 260000.0)])})

    _extract(records, echodata)

    (warning,) = printed
    assert "fm-200" in warning and "210000 Hz" in warning
    assert "between 205000 and 214000 Hz" in warning


def test_a_covered_centre_frequency_is_not_reported(records, printed):
    echodata = _EchoData({"Sonar/Beam_group1": ([CH_200], [(160000.0, 240000.0)])})

    _extract(records, echodata)

    assert printed == []


def test_without_echodata_the_centre_comes_from_the_record(records, printed):
    calibration_module.extract_standardized_calibration_parameters(
        records, {"a.raw": {CH_200: "fm-200"}}, filename="a.raw",
    )

    assert any("210000 Hz" in line for line in printed)


def test_a_curve_prints_as_a_summary_per_channel():
    curve = xr.DataArray(
        [[24.0, 25.0, np.nan], [np.nan, 27.0, 29.0]],
        dims=("cal_channel_id", "cal_frequency"),
        coords={"cal_channel_id": ["a", "b"], "cal_frequency": [30000.0, 40000.0, 50000.0]},
    )

    assert calibration_module._formatted(curve, ".2f") == [
        "2 points, 30000-40000 Hz, 24.50 at 35000 Hz",
        "2 points, 40000-50000 Hz, 28.00 at 45000 Hz",
    ]
    assert calibration_module._formatted([1.0, None], ".1f") == ["1.0", "null"]
