# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""The provenance report accounts for every channel over the whole cruise.

Modelled on HB1603, which exercises all three outcomes at once: 27 and 28 June
ran three channels at a pulse length no calibration was measured at, 3 and 7
July ran 18 and 38 kHz at twice the calibrated power, and the rest of the
cruise matched outright.
"""

from __future__ import annotations

import datetime
import json

import pytest
import yaml

from aa_si_calibration.mapping_algorithm import build_mapping
from aa_si_calibration.provenance import (
    STATUS_MATCHED,
    STATUS_OVERRIDE,
    STATUS_UNMATCHED,
    build_calibration_provenance,
    save_calibration_provenance,
)

CH_18 = "GPT  18 kHz 009072056b0e 2-1 ES18-11"
CH_38 = "GPT  38 kHz 0090720346bc 1-1 ES38B"

CAL_DURATION = 0.001024

# channel_id, transceiver_id, transducer_model, frequency, calibrated power
CHANNELS = [
    (CH_18, "009072056b0e", "ES18-11", 18000.0, 1000.0),
    (CH_38, "0090720346bc", "ES38B", 38000.0, 1000.0),
]

TOLERANCES = {
    "frequency": 1.0,
    "frequency_start": 1.0,
    "frequency_end": 1.0,
    "transmit_power": 1001.0,
    "transmit_duration_nominal": 1e-6,
}


def raw_channel(channel, power, duration):
    """One raw channel configuration at the given power and pulse length."""
    channel_id, transceiver_id, model, frequency, _ = channel
    return {
        "channel_id": channel_id,
        "transceiver_id": transceiver_id,
        "transceiver_model": "GPT",
        "transducer_model": model,
        "transducer_serial_number": None,
        "frequency": frequency,
        "frequency_start": frequency,
        "frequency_end": frequency,
        "pulse_form": "0",
        "transmit_power": power,
        "transmit_duration_nominal": duration,
        "multiplexing_found": False,
    }


def raw_file(name, start, settings):
    """One raw file configuration, twenty minutes long."""
    return {
        "filename": name,
        "file_format": "EK60",
        "first_ping_time": start.isoformat(),
        "last_ping_time": (start + datetime.timedelta(minutes=20)).isoformat(),
        "channels": [
            raw_channel(channel, *settings[channel[3]]) for channel in CHANNELS
        ],
    }


@pytest.fixture
def calibration_data():
    """Both channels calibrated at 1000 W and 1.024 ms."""
    return {
        "channels": [
            {
                "_calibration_file_key": f"2016-07-18__{int(frequency)}__config-1",
                "channel": channel_id,
                "transceiver_id": transceiver_id,
                "transducer_model": model,
                "transducer_serial_number": None,
                "pulse_form": "0",
                "frequency_start": frequency,
                "frequency_end": frequency,
                "transmit_power": power,
                "transmit_duration_nominal": CAL_DURATION,
                "calibration_date": "2016-07-18",
                "source_filenames": [f"HBB_{int(frequency // 1000):03d}kHz.cal"],
            }
            for channel_id, transceiver_id, model, frequency, power in CHANNELS
        ]
    }


@pytest.fixture
def raw_file_configs():
    """Three legs: wrong pulse length, double power, then a clean match."""
    june = {18000.0: (2000.0, 0.002048), 38000.0: (1000.0, CAL_DURATION)}
    leg_one = {18000.0: (2000.0, CAL_DURATION), 38000.0: (2000.0, CAL_DURATION)}
    leg_two = {18000.0: (1000.0, CAL_DURATION), 38000.0: (1000.0, CAL_DURATION)}

    configs = []
    for index in range(2):
        configs.append(raw_file(
            f"D20160627-T{index:06d}.raw",
            datetime.datetime(2016, 6, 27, 14) + datetime.timedelta(hours=index),
            june,
        ))
    for index in range(3):
        configs.append(raw_file(
            f"D20160703-T{index:06d}.raw",
            datetime.datetime(2016, 7, 3, 8) + datetime.timedelta(hours=index),
            leg_one,
        ))
    for index in range(4):
        configs.append(raw_file(
            f"D20160725-T{index:06d}.raw",
            datetime.datetime(2016, 7, 25, 20) + datetime.timedelta(hours=index),
            leg_two,
        ))
    return configs


@pytest.fixture
def report(raw_file_configs, calibration_data):
    """The provenance report for the three-leg cruise."""
    result = build_mapping(
        raw_file_configs, calibration_data, tolerances=TOLERANCES, verbose=False
    )
    return build_calibration_provenance(
        raw_file_configs, calibration_data, result, TOLERANCES,
        requested_tolerances={"transmit_power": 1001.0},
        unmapped_channels="warn",
        cruise_id="HB1603",
    )


def segments(report, channel_id):
    """The segments recorded for one channel."""
    return report["channels"][channel_id]["segments"]


def test_summary_counts_every_channel(report, raw_file_configs):
    """Every channel of every file lands in exactly one status."""
    summary = report["summary"]
    total = sum(len(config["channels"]) for config in raw_file_configs)
    assert summary["channels_total"] == total
    assert (
        summary["channels_matched"]
        + summary["channels_matched_under_override"]
        + summary["channels_unmatched"]
        + summary["channels_multiple_matches"]
    ) == total
    assert summary["raw_files"] == len(raw_file_configs)
    assert summary["time_start"] == "2016-06-27T14:00:00"


def test_pulse_length_segment_is_unmatched_and_says_why(report):
    """The 27 June 18 kHz files report pulse length, not power."""
    first = segments(report, CH_18)[0]
    assert first["status"] == STATUS_UNMATCHED
    assert first["outcome"] == "fallback_to_raw_file_values"
    assert first["failed_on"] == "transmit_duration_nominal"
    assert first["raw_files"] == 2
    assert first["time_start"] == "2016-06-27T14:00:00"
    assert first["comparison"]["transmit_duration_nominal"]["difference"] == (
        pytest.approx(0.001024)
    )
    # Power passed on the widened tolerance, which is what leaves pulse length
    # as the decisive field.
    assert first["comparison"]["transmit_power"]["matched"] is True
    assert "transmit_duration_nominal" in first["reason"]


def test_widened_power_segment_is_flagged_but_applied(report):
    """Leg one matched, and the report says it only matched under the override."""
    second = segments(report, CH_18)[1]
    assert second["status"] == STATUS_OVERRIDE
    assert second["outcome"] == "calibration_applied_under_override"
    assert second["calibration_key"] == "2016-07-18__18000__config-1"
    assert second["matched_only_under_override"] == ["transmit_power"]
    assert second["override_details"]["transmit_power"]["default_tolerance"] == 1.0
    assert second["override_details"]["transmit_power"]["tolerance"] == 1001.0
    assert second["raw_files"] == 3


def test_clean_segment_carries_no_override_detail(report):
    """A clean match is described by its two settings blocks and nothing more."""
    third = segments(report, CH_18)[2]
    assert third["status"] == STATUS_MATCHED
    assert third["outcome"] == "calibration_applied"
    assert "override_details" not in third
    assert "reason" not in third
    assert third["raw_settings"] == third["calibration_settings"]


def test_a_setting_change_starts_a_new_segment(report):
    """38 kHz matched throughout, but the power change still splits it."""
    entries = segments(report, CH_38)
    assert [entry["status"] for entry in entries] == [
        STATUS_MATCHED, STATUS_OVERRIDE, STATUS_MATCHED
    ]
    assert [entry["raw_files"] for entry in entries] == [2, 3, 4]


def test_segments_cover_every_file_in_time_order(report, raw_file_configs):
    """No file is dropped or counted twice, and the ranges do not overlap."""
    for channel_id in report["channels"]:
        entries = segments(report, channel_id)
        assert sum(entry["raw_files"] for entry in entries) == len(raw_file_configs)
        starts = [entry["time_start"] for entry in entries]
        assert starts == sorted(starts)
        for earlier, later in zip(entries, entries[1:]):
            assert earlier["time_end"] <= later["time_start"]


def test_tolerance_override_is_recorded(report):
    """The report names what was widened and what the default was."""
    overridden = report["tolerances"]["overridden"]
    assert overridden["transmit_power"]["default"] == 1.0
    assert overridden["transmit_power"]["applied"] == 1001.0
    assert report["tolerances"]["applied"]["transmit_duration_nominal"] == 1e-6


def test_policy_drives_the_reported_outcome(raw_file_configs, calibration_data):
    """The same unmatched channel reports differently under each policy."""
    result = build_mapping(
        raw_file_configs, calibration_data, tolerances=TOLERANCES, verbose=False
    )
    outcomes = {}
    for policy in ("warn", "error", None):
        report = build_calibration_provenance(
            raw_file_configs, calibration_data, result, TOLERANCES,
            unmapped_channels=policy,
        )
        outcomes[policy] = segments(report, CH_18)[0]["outcome"]
    assert outcomes["warn"] == "fallback_to_raw_file_values"
    assert outcomes["error"] == "run_stopped"
    assert outcomes[None] == "decided_by_consuming_step"


def test_frequency_range_failure_names_both_endpoints(calibration_data):
    """The endpoint that failed is reported, not just the one that matched."""
    settings = {18000.0: (1000.0, CAL_DURATION), 38000.0: (1000.0, CAL_DURATION)}
    config = raw_file("D1.raw", datetime.datetime(2016, 7, 25, 20), settings)
    # frequency_start still matches; only the upper edge moves.
    config["channels"] = [dict(config["channels"][0])]
    config["channels"][0]["frequency_end"] = 19500.0

    result = build_mapping(
        [config], calibration_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        [config], calibration_data, result, TOLERANCES, unmapped_channels="warn"
    )
    segment = segments(report, CH_18)[0]
    assert segment["failed_on"] == "frequency_range"
    assert "18000 to 19500" in segment["reason"]
    assert "18000 to 18000" in segment["reason"]


def test_a_channel_absent_from_later_files_does_not_span_them(calibration_data):
    """A gap ends the segment, so no time range covers files without the channel."""
    settings = {18000.0: (1000.0, CAL_DURATION), 38000.0: (1000.0, CAL_DURATION)}
    configs = [
        raw_file(
            f"D{index}.raw",
            datetime.datetime(2016, 7, 25, 20) + datetime.timedelta(hours=index),
            settings,
        )
        for index in range(4)
    ]
    # 38 kHz is missing from the two middle files.
    for config in configs[1:3]:
        config["channels"] = config["channels"][:1]

    result = build_mapping(
        configs, calibration_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        configs, calibration_data, result, TOLERANCES, unmapped_channels="warn"
    )
    entries = segments(report, CH_38)
    assert [entry["raw_files"] for entry in entries] == [1, 1]
    assert entries[0]["time_end"] < entries[1]["time_start"]
    # 18 kHz is in every file and stays one segment.
    assert len(segments(report, CH_18)) == 1


def test_multiplexing_is_reported_on_a_matched_channel(calibration_data):
    """Multiplexing does not stop a match, so it has to be said out loud."""
    settings = {18000.0: (1000.0, CAL_DURATION), 38000.0: (1000.0, CAL_DURATION)}
    configs = [
        raw_file(
            f"D{index}.raw",
            datetime.datetime(2016, 7, 25, 20) + datetime.timedelta(hours=index),
            settings,
        )
        for index in range(4)
    ]
    for config in configs[1:3]:
        config["channels"][1]["multiplexing_found"] = True

    result = build_mapping(
        configs, calibration_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        configs, calibration_data, result, TOLERANCES, unmapped_channels="warn"
    )
    assert report["summary"]["channels_multiplexed"] == 2
    entries = segments(report, CH_38)
    assert [entry["raw_files"] for entry in entries] == [1, 2, 1]
    assert all(entry["status"] == STATUS_MATCHED for entry in entries)
    assert "multiplexing" not in entries[0]
    assert "Multiplexing" in entries[1]["multiplexing"]
    assert "multiplexing" not in entries[2]


def test_sparse_channels_do_not_crash_the_report():
    """A field the raw file never recorded reads as missing, it does not raise.

    The report only describes a run, so it must not be the thing that ends one.
    """
    configs = [{"filename": "D1.raw", "channels": [{"channel_id": "ch-1"}]}]
    cal_data = {"channels": [{"channel": "ch-1", "transceiver_id": None}]}
    result = build_mapping(
        configs, cal_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        configs, cal_data, result, TOLERANCES, unmapped_channels="warn"
    )
    segment = report["channels"]["ch-1"]["segments"][0]
    assert segment["status"] == STATUS_UNMATCHED
    assert "not recorded" in segment["reason"]
    assert json.loads(json.dumps(report)) == report


def test_unnamed_calibration_channel_does_not_crash_the_report():
    """A candidate the matcher named but this lookup cannot resolve is survivable.

    find_matching_calibration reports a channel with no 'channel' key as
    'Unknown', so the report cannot recover its record to compare against.
    """
    configs = [{
        "filename": "D1.raw",
        "channels": [{
            "channel_id": "ch-1", "transceiver_id": "t1",
            "transducer_model": "M", "pulse_form": "0",
            "frequency_start": 18000.0, "frequency_end": 19500.0,
            "transmit_power": 1000.0, "transmit_duration_nominal": CAL_DURATION,
        }],
    }]
    cal_data = {"channels": [{
        "transceiver_id": "t1", "transducer_model": "M", "pulse_form": "0",
        "frequency_start": 18000.0, "frequency_end": 18000.0,
        "transmit_power": 1000.0, "transmit_duration_nominal": CAL_DURATION,
    }]}
    result = build_mapping(
        configs, cal_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        configs, cal_data, result, TOLERANCES, unmapped_channels="warn"
    )
    segment = report["channels"]["ch-1"]["segments"][0]
    assert segment["failed_on"] == "frequency_range"
    assert "frequency_range" in segment["reason"]
    assert json.loads(json.dumps(report)) == report


def test_report_is_json_safe(report):
    """A server can hand the report to a client without touching disk."""
    assert json.loads(json.dumps(report)) == report


def test_written_file_round_trips(report, tmp_path):
    """The YAML on disk carries the same content as the returned dict."""
    path = save_calibration_provenance(report, tmp_path)
    assert path.name == "calibration_provenance.yaml"
    assert yaml.safe_load(path.read_text()) == report


def test_clean_cruise_reports_one_segment_per_channel(calibration_data):
    """Nothing to flag collapses to a single segment and an empty override map."""
    settings = {18000.0: (1000.0, CAL_DURATION), 38000.0: (1000.0, CAL_DURATION)}
    configs = [
        raw_file(
            f"D20160725-T{index:06d}.raw",
            datetime.datetime(2016, 7, 25, 20) + datetime.timedelta(hours=index),
            settings,
        )
        for index in range(5)
    ]
    result = build_mapping(
        configs, calibration_data, tolerances=TOLERANCES, verbose=False
    )
    report = build_calibration_provenance(
        configs, calibration_data, result, TOLERANCES, unmapped_channels="warn"
    )
    assert report["summary"]["channels_unmatched"] == 0
    assert report["summary"]["channels_matched_under_override"] == 0
    for channel_id in report["channels"]:
        entries = segments(report, channel_id)
        assert len(entries) == 1
        assert entries[0]["status"] == STATUS_MATCHED
        assert entries[0]["raw_files"] == 5
