# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Pytest configuration and fixtures."""

from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Paths – example data (read-only inputs, never written to)
# ---------------------------------------------------------------------------

_EXAMPLE_DATA = (
    Path(__file__).parent.parent / "notebooks" / "example_data"
)


@pytest.fixture(scope="session")
def example_data_dir():
    return _EXAMPLE_DATA


@pytest.fixture(scope="session")
def ek60_raw_dir():
    return _EXAMPLE_DATA / "ek60_raw_file_input_folder"


@pytest.fixture(scope="session")
def ek60_cal_dir():
    return _EXAMPLE_DATA / "ek60_cal_file_input_folder"


@pytest.fixture(scope="session")
def ek60_single_channel_dir():
    return _EXAMPLE_DATA / "ek60_single_channel_yml_cal_files_input"


@pytest.fixture(scope="session")
def ek80_cw_raw_dir():
    return _EXAMPLE_DATA / "ek80_CW_raw_file_input_folder"


@pytest.fixture(scope="session")
def ek80_cal_dir():
    return _EXAMPLE_DATA / "ek80_cal_file_input_folder"


@pytest.fixture(scope="session")
def ek80_fm_raw_dir():
    return _EXAMPLE_DATA / "ek80_FM_raw_file_input_folder"


@pytest.fixture(scope="session")
def ek80_fm_cal_dir():
    return _EXAMPLE_DATA / "ek80_FM_cal_file_input_folder"


@pytest.fixture(scope="session")
def hb2407_raw_dir():
    return _EXAMPLE_DATA / "HB2407_raw"


@pytest.fixture(scope="session")
def hb2407_cal_dir():
    return _EXAMPLE_DATA / "HB2407_cal"


# ---------------------------------------------------------------------------
# Temporary output directory (fresh per test)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_output_dir(tmp_path):
    """Return a dict of Path objects for the standard pipeline output layout."""
    dirs = {
        "base": tmp_path,
        "raw_configs": tmp_path / "raw_file_configs",
        "single_cal": tmp_path / "single_channel_calibration_files",
        "mapping": tmp_path / "mapping_files",
        "logs": tmp_path / "logs",
        "unused": tmp_path / "unused_calibration_files",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs
