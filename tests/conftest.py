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


# ---------------------------------------------------------------------------
# Standardized calibration records
# ---------------------------------------------------------------------------

@pytest.fixture
def calibration_record():
    """Factory for a complete, schema-valid CW standardized record.

    Two records from it differ only in the fields passed, so they match the
    same raw channel and can be averaged.
    """
    def make(key=None, **overrides):
        record = {
            "source_filenames": ["CalibrationDataFile-D20230627-T181441-38kHz.xml"],
            "record_created": "2026-01-01T00:00:00+00:00",
            "record_author": "Calibrator",
            "channel": "ES38-7 Serial No: 337",
            "transceiver_id": "987763",
            "transceiver_model": "WBT",
            "transducer_model": "ES38-7",
            "transducer_serial_number": "337",
            "pulse_form": "0",
            "frequency_start": 38000.0,
            "frequency_end": 38000.0,
            "nominal_transducer_frequency": 38000.0,
            "transmit_power": 2000.0,
            "transmit_duration_nominal": 0.001024,
            "multiplexing_found": False,
            "calibration_date": ["2023-06-27"],
            "is_averaged": False,
            "calibration_comments": "Pre-cruise calibration",
            "absorption_indicative": 0.0098,
            "sound_speed_indicative": 1490.0,
            "temperature": 12.0,
            "salinity": 32.0,
            "sample_interval": 0.000256,
            "transmit_bandwidth": 2425.0,
            "beam_type": "BeamTypeSplit",
            "sphere_diameter": 38.1,
            "sphere_material": "tungsten carbide",
            "source_file_type": ".xml",
            "sonar_software_name": "EK80",
            "equivalent_beam_angle": -20.7,
            "gain_correction": [25.0],
            "sa_correction": [-0.1],
            "frequency": [38000.0],
            "beamwidth_transmit_major": [7.0],
            "beamwidth_receive_major": [7.0],
            "beamwidth_transmit_minor": [7.0],
            "beamwidth_receive_minor": [7.0],
            "echoangle_major": [0.1],
            "echoangle_minor": [-0.05],
        }
        record.update(overrides)
        if key is not None:
            record["_calibration_file_key"] = key
        return record

    return make
