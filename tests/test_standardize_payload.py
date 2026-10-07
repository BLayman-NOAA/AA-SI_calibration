# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for the standardized channels carried as data rather than as files.

``single_channel_data`` is what a caller with no access to the outputs folder
reviews, and what comes back as ``override_channels`` once it has been edited.
Two properties make that round trip safe, and neither fails loudly on its own:
the payload has to equal a read of the folder it describes, and it has to be
JSON so the checkpoint layer stores it as JSON rather than as a pickle the
shared survey cache tier refuses.
"""

import datetime
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from aa_si_calibration import calibration as calibration_module
from aa_si_calibration import standardized_file_lib as sfl


def _channel(**overrides):
    """A schema-valid standardized channel."""
    channel = {
        "channel": "ES38-7 Serial No: 337 - Narrow",
        "frequency": [38000.0],
        "calibration_date": ["2023-06-27"],
        "source_filenames": ["cal_38kHz_CW.xml"],
        "transducer_model": "ES38-7",
        "transducer_serial_number": "337",
        "pulse_form": "CW",
        "nominal_transducer_frequency": 38000,
        "transmit_power": 2000.0,
        "transmit_duration_nominal": 0.001024,
        "frequency_start": 38000,
        "frequency_end": 38000,
    }
    channel.update(overrides)
    return channel


def _write(channels, out_dir):
    """Save *channels* and return the payload describing what was written."""
    sfl.save_single_channel_files(channels, out_dir, short_filenames=True)
    return sfl.single_channel_payload(
        sfl.assign_calibration_file_stems(channels, short_filenames=True)
    )


def _stems(out_dir):
    return sorted(p.stem for p in out_dir.glob("*.yaml"))


# ---------------------------------------------------------------------------
# json_safe
# ---------------------------------------------------------------------------


def test_json_safe_coerces_every_type_a_yaml_round_trip_produces():
    """An unquoted date and a numpy scalar both survive YAML but not JSON."""
    coerced = sfl.json_safe(
        {
            "numpy_float": np.float64(2000.0),
            "numpy_int": np.int64(38000),
            "decimal": Decimal("1.5"),
            "date": datetime.date(2023, 6, 27),
            "timestamp": datetime.datetime(2023, 6, 27, 12, 0, 0),
            "path": Path("a") / "b.yaml",
            "tuple": (1, 2),
            38000: "an int key",
        }
    )
    json.dumps(coerced)

    assert coerced["numpy_float"] == 2000.0
    assert not isinstance(coerced["numpy_float"], np.generic)
    assert coerced["numpy_int"] == 38000
    assert coerced["decimal"] == 1.5
    assert coerced["date"] == "2023-06-27"
    assert coerced["timestamp"].startswith("2023-06-27T12:00:00")
    assert coerced["path"] in ("a/b.yaml", "a\\b.yaml")
    assert coerced["tuple"] == [1, 2]
    assert coerced["38000"] == "an int key"


def test_json_safe_leaves_a_bool_a_bool():
    """bool subclasses int, so an over-eager numeric branch would flatten it."""
    assert sfl.json_safe({"skipped": True}) == {"skipped": True}
    assert sfl.json_safe({"skipped": True})["skipped"] is True


# ---------------------------------------------------------------------------
# The payload against the folder it describes
# ---------------------------------------------------------------------------


def test_payload_equals_a_read_of_the_folder(tmp_path):
    """The whole premise: in-memory data and the written files agree.

    A caller may receive either, depending on whether the parse ran or the
    reuse guard short-circuited it, and must not be able to tell them apart.
    """
    out_dir = tmp_path / "single_channel_calibration_files"
    in_memory = _write([_channel(), _channel(transmit_power=1000.0)], out_dir)

    assert in_memory == calibration_module._payload_from_dir(out_dir)


def test_payload_is_json(tmp_path):
    """Not JSON means checkpointed as a pickle, which the survey tier rejects."""
    out_dir = tmp_path / "single_channel_calibration_files"
    payload = _write([_channel()], out_dir)

    assert json.loads(json.dumps(payload)) == payload


def test_payload_carries_the_file_stem_as_the_key(tmp_path):
    """The mapping is built on stems, so that is what has to round trip."""
    out_dir = tmp_path / "single_channel_calibration_files"
    payload = _write([_channel(), _channel(transmit_power=1000.0)], out_dir)

    keys = [c["_calibration_file_key"] for c in payload["channels"]]
    assert keys == _stems(out_dir)
    assert keys == ["2023-06-27__38000__config-1", "2023-06-27__38000__config-2"]


def test_payload_orders_config_numbers_numerically(tmp_path):
    """A plain string sort puts config-10 before config-2.

    The caller sends the payload back in this order and the config numbers are
    reassigned from it, so the wrong order would renumber every file.
    """
    out_dir = tmp_path / "single_channel_calibration_files"
    channels = [_channel(transmit_power=float(p)) for p in range(1000, 1012)]
    payload = _write(channels, out_dir)

    numbers = [
        int(c["_calibration_file_key"].rsplit("-", 1)[1]) for c in payload["channels"]
    ]
    assert numbers == sorted(numbers)


# ---------------------------------------------------------------------------
# override_channels
# ---------------------------------------------------------------------------


def test_unedited_channels_round_trip_to_the_same_filenames(tmp_path):
    """Sending the payload straight back has to be a no-op on the folder.

    Conflict ids are derived from these names, so a rename between the report
    and the decision would invalidate the choices the caller just made.
    """
    parsed = tmp_path / "parsed"
    replayed = tmp_path / "replayed"
    payload = _write([_channel(), _channel(transmit_power=1000.0)], parsed)

    prepared = sfl.prepare_override_channels(payload["channels"])
    sfl.save_single_channel_files(prepared, replayed, short_filenames=True)

    assert _stems(replayed) == _stems(parsed)


def test_prepare_ignores_the_incoming_file_key(tmp_path):
    """Names are re-derived, so a stale key cannot pin a file in place."""
    prepared = sfl.prepare_override_channels(
        [_channel(_calibration_file_key="something-else")]
    )
    assert "_calibration_file_key" not in prepared[0]

    out_dir = tmp_path / "out"
    sfl.save_single_channel_files(prepared, out_dir, short_filenames=True)
    assert _stems(out_dir) == ["2023-06-27__38000__config-1"]


def test_an_edited_value_is_rounded_rather_than_refused():
    """Validation rejects excess decimals instead of trimming them.

    Rounding has to run first or a value typed in a browser is an error rather
    than a correction.
    """
    prepared = sfl.prepare_override_channels(
        [_channel(transmit_power=1999.999999999)]
    )
    assert prepared[0]["transmit_power"] == pytest.approx(2000.0, abs=0.01)


def test_an_invalid_edit_is_rejected():
    """The schema is the guard between a caller's edits and the archive."""
    import jsonschema

    with pytest.raises(jsonschema.ValidationError):
        sfl.prepare_override_channels([_channel(pulse_form=0)])


def test_overrides_replace_the_folder_rather_than_adding_to_it(tmp_path):
    """A discarded channel must not survive as an orphan.

    build_mapping globs this folder, so a file left behind is still matched and
    still archived.
    """
    out_dir = tmp_path / "out" / "single_channel_calibration_files"
    _write([_channel(), _channel(transmit_power=1000.0)], out_dir)
    assert len(_stems(out_dir)) == 2

    calibration_module._write_override_channels(
        {"channels": [_channel()]},
        out_dir,
        tmp_path / "out" / "standardization.fingerprint.json",
        {"version": 1},
        verbose=False,
    )
    assert _stems(out_dir) == ["2023-06-27__38000__config-1"]


def test_override_result_matches_the_folder_it_wrote(tmp_path):
    out_dir = tmp_path / "out" / "single_channel_calibration_files"
    out_dir.mkdir(parents=True)

    result = calibration_module._write_override_channels(
        {"channels": [_channel(), _channel(transmit_power=1000.0)]},
        out_dir,
        tmp_path / "out" / "standardization.fingerprint.json",
        {"version": 1},
        verbose=False,
    )

    assert result["channel_count"] == 2
    assert result["skipped"] is False
    assert result["single_channel_data"] == calibration_module._payload_from_dir(out_dir)
    json.dumps(result["single_channel_data"])


def test_a_bare_channel_list_is_accepted(tmp_path):
    """Callers hand back either the payload or the list inside it."""
    out_dir = tmp_path / "out" / "single_channel_calibration_files"
    out_dir.mkdir(parents=True)

    result = calibration_module._write_override_channels(
        [_channel()],
        out_dir,
        tmp_path / "out" / "standardization.fingerprint.json",
        {"version": 1},
        verbose=False,
    )
    assert result["channel_count"] == 1


# ---------------------------------------------------------------------------
# The fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_without_overrides_is_unchanged(tmp_path):
    """No override digest when none were supplied.

    An extra key would make every sidecar written before overrides existed look
    stale and force one pointless re-parse of the whole survey.
    """
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    (cal_dir / "a.cal").write_text("cal", encoding="utf-8")

    plain = calibration_module._standardization_fingerprint(cal_dir, None, True)
    explicit_none = calibration_module._standardization_fingerprint(
        cal_dir, None, True, None
    )

    assert "override_digest" not in plain
    assert plain == explicit_none


def test_supplied_overrides_change_the_fingerprint(tmp_path):
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    (cal_dir / "a.cal").write_text("cal", encoding="utf-8")

    plain = calibration_module._standardization_fingerprint(cal_dir, None, True)
    edited = calibration_module._standardization_fingerprint(
        cal_dir, None, True, {"channels": [_channel()]}
    )
    edited_again = calibration_module._standardization_fingerprint(
        cal_dir, None, True, {"channels": [_channel(transmit_power=1000.0)]}
    )

    assert edited != plain
    assert edited != edited_again


# ---------------------------------------------------------------------------
# calibration_date as a list
# ---------------------------------------------------------------------------

def test_a_string_calibration_date_reads_as_a_list(tmp_path):
    """Files written before dates became a list still load."""
    from aa_si_calibration.mapping_algorithm import load_calibration_data_from_single_files

    (tmp_path / "quoted.yaml").write_text('channel: "a"\ncalibration_date: "7/18/2016"\n')
    (tmp_path / "unquoted.yaml").write_text('channel: "b"\ncalibration_date: 2016-07-18\n')

    channels = load_calibration_data_from_single_files(tmp_path)["channels"]

    assert [c["calibration_date"] for c in channels] == [["2016-07-18"], ["2016-07-18"]]


def test_a_single_date_key_is_unchanged_by_the_list_form():
    """Existing file names, mapping keys and conflict ids stay as they were."""
    assert sfl.build_calibration_key(_channel()) == sfl.build_calibration_key(
        _channel(calibration_date="2023-06-27")
    )
    assert sfl.build_calibration_key(_channel()).startswith("2023-06-27__")


def test_override_channels_accept_a_string_date():
    """An older client sends the string form back."""
    (prepared,) = sfl.prepare_override_channels([_channel(calibration_date="2023-06-27")])

    assert prepared["calibration_date"] == ["2023-06-27"]
