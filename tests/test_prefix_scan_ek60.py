# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for reading an EK60 channel configuration from a file's leading bytes.

EK60 needs its own completeness rule, and the reason is a trap worth pinning
down. CON0 carries a *configured* transmit power for every channel, so a short
prefix yields a channel that looks complete but reports the header default
instead of what the transceiver actually transmitted. The real value only
arrives with that channel's first RAW0 datagram.

Measured on HB1603_L1-D20160707-T192446 (52.6 MB, five channels): a 64 KiB
prefix reports 2000 W for all five, while the file's real values are 2000,
2000, 500, 300 and 750 W. Three channels silently wrong, in a parameter that
feeds straight into Sv. At 256 KiB the first ping cycle is complete and every
value is right.

These tests hold that line: a prefix short of one RAW0 per channel must be
rejected, not reported.
"""

from pathlib import Path

import pytest

from aa_si_calibration.calibration import _channels_are_complete
from aa_si_calibration.raw_reader_api import detect_instrument_type, process_raw_file

REPO = Path(__file__).resolve().parent.parent
EK60_DIR = REPO / "notebooks" / "example_data" / "ek60_raw_file_input_folder"


def _ek60_files():
    return sorted(EK60_DIR.glob("*.raw")) if EK60_DIR.exists() else []


def _truncate(raw_path, tmp_path, n_bytes):
    prefix = tmp_path / f"{n_bytes}_{raw_path.name}"
    with open(raw_path, "rb") as src:
        prefix.write_bytes(src.read(n_bytes))
    return prefix


requires_ek60 = pytest.mark.skipif(
    not _ek60_files(), reason="EK60 example data not available"
)


# ---------------------------------------------------------------------------
# The completeness rule itself
# ---------------------------------------------------------------------------


def _config(n_channels=5, raw0_count=None, power=2000.0):
    return {
        "raw0_count": raw0_count,
        "channels": [
            {
                "channel_id": f"GPT {i}",
                "transmit_duration_nominal": 0.001024,
                "transmit_power": power,
            }
            for i in range(n_channels)
        ],
    }


def test_ek60_rejects_a_prefix_that_has_not_seen_every_channel_transmit():
    """The whole point: values present but not yet read from a ping."""
    assert not _channels_are_complete(_config(raw0_count=2), "EK60")


def test_ek60_accepts_one_raw0_per_channel():
    assert _channels_are_complete(_config(raw0_count=5), "EK60")


def test_ek60_accepts_more_raw0_than_channels():
    assert _channels_are_complete(_config(raw0_count=860), "EK60")


def test_ek60_rejects_a_missing_raw0_count():
    assert not _channels_are_complete(_config(raw0_count=None), "EK60")


def test_ek60_still_requires_the_shared_fields():
    config = _config(raw0_count=5)
    config["channels"][2]["transmit_power"] = None
    assert not _channels_are_complete(config, "EK60")


def test_ek80_is_unaffected_by_the_raw0_rule():
    """EK80 has no RAW0 at all; its rule must not start demanding one."""
    assert _channels_are_complete(_config(raw0_count=None), "EK80")


def test_the_default_instrument_stays_ek80():
    """Existing callers pass one argument and must keep the old behaviour."""
    assert _channels_are_complete(_config(raw0_count=None))


def test_no_channels_is_never_complete():
    assert not _channels_are_complete({"channels": [], "raw0_count": 99}, "EK60")


# ---------------------------------------------------------------------------
# Against the real EK60 files
# ---------------------------------------------------------------------------


@requires_ek60
@pytest.mark.parametrize("raw_path", _ek60_files(), ids=lambda p: p.name)
def test_files_are_detected_as_ek60(raw_path):
    assert detect_instrument_type(raw_path) == "EK60"


@requires_ek60
@pytest.mark.parametrize("raw_path", _ek60_files(), ids=lambda p: p.name)
def test_a_short_prefix_is_rejected_rather_than_trusted(raw_path, tmp_path):
    """64 KiB parses and yields channels, and must still be judged incomplete."""
    config = process_raw_file(_truncate(raw_path, tmp_path, 64 * 2**10), verbose=False)
    if config is None or not config.get("channels"):
        pytest.skip("64 KiB does not parse for this file")

    assert (config.get("raw0_count") or 0) < len(config["channels"])
    assert not _channels_are_complete(config, "EK60")


@requires_ek60
@pytest.mark.parametrize("raw_path", _ek60_files(), ids=lambda p: p.name)
def test_a_settled_prefix_matches_the_whole_file(raw_path, tmp_path):
    """Once accepted, the prefix config must equal the whole-file config."""
    whole = process_raw_file(raw_path, verbose=False)

    settled = None
    for n_bytes in (256 * 2**10, 1024 * 2**10, 4 * 2**20):
        config = process_raw_file(_truncate(raw_path, tmp_path, n_bytes), verbose=False)
        if config is not None and _channels_are_complete(config, "EK60"):
            settled = config
            break
    assert settled is not None, "no prefix up to 4 MiB settled the configuration"

    assert settled["channels"] == whole["channels"]


@requires_ek60
@pytest.mark.parametrize("raw_path", _ek60_files(), ids=lambda p: p.name)
def test_transmit_power_is_the_transmitted_value_not_the_header_default(
    raw_path, tmp_path
):
    """The specific failure this rule exists to prevent."""
    whole = process_raw_file(raw_path, verbose=False)
    truth = {c["channel_id"]: c["transmit_power"] for c in whole["channels"]}

    short = process_raw_file(_truncate(raw_path, tmp_path, 64 * 2**10), verbose=False)
    if short is None or not short.get("channels"):
        pytest.skip("64 KiB does not parse for this file")
    from_short = {c["channel_id"]: c["transmit_power"] for c in short["channels"]}

    # If the short prefix happened to agree everywhere the trap would not be
    # reachable on this file, and the rule below is what stops it being used.
    if from_short != truth:
        assert not _channels_are_complete(short, "EK60")
