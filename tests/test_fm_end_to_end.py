# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""A merged FM calibration calibrates real EK80 broadband data through echopype.

The example cruise calibrated its ES200 with a 38.1 mm sphere on 2023-07-20 and
a 22 mm sphere on 2023-07-21. The 38.1 mm sphere is not valid at 205-214 kHz,
which holds the channel's 210 kHz centre frequency; the 22 mm sphere is.
"""

import contextlib
import io

import numpy as np
import pytest

from aa_si_calibration import _console
from aa_si_calibration.calibration import (
    build_calibration_mapping,
    extract_standardized_calibration_parameters,
    record_raw_file_configs,
    standardize_calibration_files,
)
from aa_si_calibration.raw_reader_api import process_raw_folder

RAW_FILE = "D20230721-T174615.raw"
CH_200 = "WBT 400509-15 ES200-7C_ES"
LARGE_200 = "2023-07-20__200000__config-2"
SMALL_200 = "2023-07-21__200000__config-1"


@pytest.fixture
def survey(tmp_path, request):
    """The example raw folder scanned and its calibrations standardized.

    Per test, since resolving the conflicts sets the losing files aside.
    """
    example = request.config.rootpath / "notebooks/example_data"
    out = tmp_path
    with contextlib.redirect_stdout(io.StringIO()):
        configs, _ = process_raw_folder(example / "ek80_FM_raw_file_input_folder", verbose=False)
        recorded = record_raw_file_configs(configs, out, verbose=False)
        standardize_calibration_files(
            example / "ek80_FM_cal_file_input_folder", out,
            frequencies=recorded["frequencies"], cruise_id="TEST",
            record_author="Tester", verbose=False,
        )
        conflicts = build_calibration_mapping(
            out, conflict_resolution="report", verbose=False,
        )["conflicts"]
    return out, conflicts, example / "ek80_FM_raw_file_input_folder" / RAW_FILE


def _choices(conflicts, choice_200):
    """The 200 kHz conflict answered with *choice_200*, the others with one key."""
    choices = {}
    for conflict_id, conflict in conflicts.items():
        keys = conflict["candidate_keys"]
        choices[conflict_id] = choice_200 if LARGE_200 in keys else keys[-1]
    return choices


def _calibrate(survey, choice_200, printed):
    import echopype as ep

    out, conflicts, raw_path = survey
    with contextlib.redirect_stdout(io.StringIO()):
        done = build_calibration_mapping(
            out, conflict_resolution="report", verbose=False,
            calibration_choices=_choices(conflicts, choice_200),
        )
    echodata = ep.open_raw(raw_path, sonar_model="EK80")
    printed.clear()
    params = extract_standardized_calibration_parameters(
        done["calibration_dict"], done["mapping_dict"], filename=RAW_FILE,
        echodata=echodata, waveform_mode="BB", encode_mode="complex",
    )
    sv = ep.calibrate.compute_Sv(
        echodata, waveform_mode="BB", encode_mode="complex",
        cal_params=params["cal_params"], env_params=params["env_params"],
    )
    return done, params, sv


@pytest.fixture
def printed(monkeypatch):
    lines = []
    monkeypatch.setattr(
        _console, "console_print", lambda *a, **_k: lines.append(" ".join(map(str, a)))
    )
    return lines


@pytest.mark.slow
def test_a_merged_calibration_calibrates_broadband_data(survey, printed):
    done, params, sv = _calibrate(survey, {"merge": [SMALL_200, LARGE_200]}, printed)

    gain = params["cal_params"]["gain_correction"]
    assert CH_200 in gain["cal_channel_id"].values
    assert "WBT 400479-15 ES18_ES" not in gain["cal_channel_id"].values
    assert np.isfinite(sv["Sv"].sel(channel=CH_200).values).mean() > 0.9
    assert printed == []

    (merged,) = [k for k, e in done["provenance"]["calibration_files"].items() if e["is_merged"]]
    assert done["provenance"]["calibration_files"][merged]["holes_hz"] == [
        [163000.0, 170010.0], [240000.0, 245000.0],
    ]


@pytest.mark.slow
def test_the_large_sphere_alone_misses_the_centre_frequency(survey, printed):
    _calibrate(survey, LARGE_200, printed)

    assert any(
        LARGE_200 in line and "210000 Hz" in line and "between 205000 and 214000 Hz" in line
        for line in printed
    )
