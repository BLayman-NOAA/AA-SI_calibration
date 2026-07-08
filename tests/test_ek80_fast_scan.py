# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Regression tests for the single pass EK80 raw scanner and mapping coverage.

These import only raw_reader_api and mapping_algorithm so they do not pull in
echopype (which calibration.py imports at module load). They cover the fast
path added for EK80 config extraction and the channel mapping coverage check.
"""

from pathlib import Path

import pytest

from aa_si_calibration.raw_reader_api import (
    process_raw_folder,
    scan_ek80_file,
    read_ek80_xml_as_dict,
    extract_ek80_datagram_timestamps,
    extract_gps_data,
)
from aa_si_calibration.mapping_algorithm import verify_mapping_covers_raw_files

REPO = Path(__file__).resolve().parent.parent
RAW_CAL = REPO / "notebooks" / "example_data" / "HB2407_raw_cal"
EK60 = REPO / "notebooks" / "example_data" / "ek60_raw_file_input_folder"


def _ek80_files():
    return sorted(RAW_CAL.glob("*.raw"))


@pytest.mark.skipif(not RAW_CAL.exists(), reason="HB2407 example data not available")
@pytest.mark.parametrize("raw_path", _ek80_files(), ids=lambda p: p.name)
def test_scan_matches_individual_wrappers(raw_path):
    """The combined single pass agrees with each standalone extractor."""
    scan = scan_ek80_file(raw_path)
    assert scan["xml_dicts"] == read_ek80_xml_as_dict(raw_path)
    assert scan["timestamps"] == extract_ek80_datagram_timestamps(raw_path)
    assert scan["gps_data"] == extract_gps_data(raw_path)


@pytest.mark.skipif(not RAW_CAL.exists(), reason="HB2407 example data not available")
def test_fast_path_matches_reader_verified():
    """The fast start time equals the reader START_TIME for these files.

    verify_start_time=True runs the full SimradFileReader (the pre refactor
    behaviour); the default fast path must produce identical file configs.
    """
    fast, _ = process_raw_folder(RAW_CAL, verbose=False, verify_start_time=False)
    verified, _ = process_raw_folder(RAW_CAL, verbose=False, verify_start_time=True)
    assert fast == verified


@pytest.mark.skipif(not EK60.exists(), reason="EK60 example data not available")
def test_ek60_path_still_extracts_channels_and_gps():
    """The EK60 branch (still reader based) and shared GPS parsing keep working."""
    configs, _ = process_raw_folder(EK60, verbose=False)
    assert configs
    for cfg in configs:
        assert cfg["instrument"] == "EK60"
        assert cfg["channels"]
        assert "gps_data" in cfg


def test_verify_mapping_covers_raw_files():
    """The coverage check passes on a full mapping and fails on missing/extra."""
    configs = [
        {"filename": "a.raw", "channels": []},
        {"filename": "b.raw", "channels": []},
    ]
    assert verify_mapping_covers_raw_files({"a.raw": {}, "b.raw": {"ch": "k"}}, configs)
    assert not verify_mapping_covers_raw_files({"a.raw": {}}, configs)
    assert not verify_mapping_covers_raw_files(
        {"a.raw": {}, "b.raw": {}, "c.raw": {}}, configs
    )


def test_verify_mapping_covers_raw_files_from_path(tmp_path):
    """The check accepts a channel_mapping.yaml path, as the notebook passes it."""
    import yaml

    configs = [{"filename": "a.raw", "channels": []}]
    mapping_path = tmp_path / "channel_mapping.yaml"
    mapping_path.write_text(yaml.safe_dump({"a.raw": {"ch": "k"}}))
    assert verify_mapping_covers_raw_files(mapping_path, configs)
