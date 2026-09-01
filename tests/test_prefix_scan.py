# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for reading an EK80 channel configuration from a file's leading bytes.

The prefix scan exists so a remote survey can be scanned without transferring
every raw file whole. These cover the two things that has to get right: the
configuration a prefix yields must equal the one the whole file yields, and a
prefix too short to reach every channel's Parameter datagram must be rejected
rather than reported.
"""

from pathlib import Path

import pytest

from aa_si_calibration.calibration import (
    _channels_are_complete,
    _read_config_from_prefix,
    read_raw_file_config,
)
from aa_si_calibration.raw_reader_api import process_raw_file

REPO = Path(__file__).resolve().parent.parent
EK80_DIRS = [
    REPO / "notebooks" / "example_data" / "HB2407_raw_cal",
    REPO / "notebooks" / "example_data" / "ek80_CW_raw_file_input_folder",
    REPO / "notebooks" / "example_data" / "ek80_FM_raw_file_input_folder",
]

PREFIX_BYTES = 8 * 2**20


def _ek80_files():
    return [p for d in EK80_DIRS if d.exists() for p in sorted(d.glob("*.raw"))]


def _truncate(raw_path, tmp_path, n_bytes):
    prefix = tmp_path / raw_path.name
    with open(raw_path, "rb") as src:
        prefix.write_bytes(src.read(n_bytes))
    return prefix


@pytest.mark.skipif(not _ek80_files(), reason="EK80 example data not available")
@pytest.mark.parametrize("raw_path", _ek80_files(), ids=lambda p: p.name)
def test_prefix_channels_match_whole_file(raw_path, tmp_path):
    """An 8 MiB prefix yields the same channel configuration as the whole file."""
    whole = process_raw_file(raw_path, verbose=False)
    prefix = process_raw_file(_truncate(raw_path, tmp_path, PREFIX_BYTES), verbose=False)

    assert _channels_are_complete(prefix)
    assert prefix["channels"] == whole["channels"]
    assert prefix["metadata_start_time"] == whole["metadata_start_time"]
    assert prefix["first_ping_time"] == whole["first_ping_time"]


@pytest.mark.skipif(not _ek80_files(), reason="EK80 example data not available")
@pytest.mark.parametrize("raw_path", _ek80_files(), ids=lambda p: p.name)
def test_default_prefix_size_covers_these_files(raw_path, tmp_path):
    """The bytes needed to settle the configuration fit inside the default.

    FM files need the most, because their Parameter datagrams sit behind
    correspondingly larger RAW3 payloads. This is what PREFIX_BYTES is sized
    against, so a file that needed more would be worth knowing about.
    """
    size = raw_path.stat().st_size
    ladder = []
    for step in (64, 128, 256, 512, 1024, 2048, 4096, 8192):
        probe = min(step * 2**10, size)
        if probe <= PREFIX_BYTES and probe not in ladder:
            ladder.append(probe)

    needed = None
    for probe in ladder:
        config = process_raw_file(_truncate(raw_path, tmp_path, probe), verbose=False)
        if config is not None and _channels_are_complete(config):
            needed = probe
            break

    assert needed is not None, f"configuration not settled within {PREFIX_BYTES} bytes"
    assert needed <= PREFIX_BYTES


def test_configuration_only_prefix_is_rejected(tmp_path):
    """A prefix reaching the Configuration but no Parameter datagram is refused.

    80 KiB clears the Configuration datagram on these files and stops well
    before the first Parameter block, which is exactly the case that would
    otherwise report an FM channel as CW with no transmit power.
    """
    files = _ek80_files()
    if not files:
        pytest.skip("EK80 example data not available")

    config = process_raw_file(_truncate(files[0], tmp_path, 80 * 2**10), verbose=False)
    assert config is None or not _channels_are_complete(config)


def test_channels_are_complete_rejects_partial_channels():
    """The guard fails a channel missing either Parameter-derived value."""
    assert _channels_are_complete(
        {"channels": [{"transmit_duration_nominal": 0.001, "transmit_power": 2000.0}]}
    )
    assert not _channels_are_complete({"channels": []})
    assert not _channels_are_complete({"channels": [{"transmit_power": 2000.0}]})
    assert not _channels_are_complete(
        {"channels": [{"transmit_duration_nominal": 0.001, "transmit_power": None}]}
    )


@pytest.mark.skipif(not _ek80_files(), reason="EK80 example data not available")
def test_remote_prefix_scan_matches_whole_file_scan(tmp_path):
    """Over a remote URL, the prefix path reproduces the whole-file channels.

    Uses fsspec's in-memory filesystem so the remote branch runs without cloud
    credentials. read_raw_file_config sees a non-local URL and takes the same
    code path it takes for gs://.
    """
    fsspec = pytest.importorskip("fsspec")

    raw_path = _ek80_files()[0]
    url = f"memory://survey/{raw_path.name}"
    fs = fsspec.filesystem("memory")
    fs.mkdirs("/survey", exist_ok=True)
    with open(raw_path, "rb") as src, fs.open(f"/survey/{raw_path.name}", "wb") as dst:
        dst.write(src.read())

    try:
        from_prefix = _read_config_from_prefix(url, PREFIX_BYTES, None, verbose=False)
        assert from_prefix is not None

        whole = process_raw_file(raw_path, verbose=False)
        assert from_prefix["channels"] == whole["channels"]
        assert from_prefix["last_ping_time"] == whole["last_ping_time"]
        assert from_prefix["raw3_count"] is None
        assert from_prefix["gps_data"] is None

        via_op = read_raw_file_config(url, verbose=False, max_scan_bytes=PREFIX_BYTES)
        assert via_op["channels"] == from_prefix["channels"]
    finally:
        fs.rm("/survey", recursive=True)


@pytest.mark.skipif(not _ek80_files(), reason="EK80 example data not available")
def test_short_prefix_falls_back_to_whole_file(tmp_path):
    """A prefix too short to settle the configuration still returns it in full.

    The fallback is what keeps max_scan_bytes safe to set: an unusual file
    costs a whole-file read rather than a wrong answer.
    """
    fsspec = pytest.importorskip("fsspec")

    raw_path = _ek80_files()[0]
    url = f"memory://short/{raw_path.name}"
    fs = fsspec.filesystem("memory")
    fs.mkdirs("/short", exist_ok=True)
    with open(raw_path, "rb") as src, fs.open(f"/short/{raw_path.name}", "wb") as dst:
        dst.write(src.read())

    try:
        assert _read_config_from_prefix(url, 80 * 2**10, None, verbose=False) is None

        config = read_raw_file_config(url, verbose=False, max_scan_bytes=80 * 2**10)
        whole = process_raw_file(raw_path, verbose=False)
        assert config["channels"] == whole["channels"]
        assert config["raw3_count"] == whole["raw3_count"]
    finally:
        fs.rm("/short", recursive=True)
