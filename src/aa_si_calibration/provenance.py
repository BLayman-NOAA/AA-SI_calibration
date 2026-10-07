# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Per-channel provenance for the calibration mapping.

The matcher already knows, for every raw channel it looked at, whether a
calibration file matched, whether it matched only because a tolerance was
widened, and which field the closest candidate failed on. That knowledge
reaches the terminal as a handful of warnings and the step log as one block per
channel, neither of which survives a long run. This module turns it into one
small file.

The report is built at mapping time, so it covers every file in the catalogue
even when the per-file tier that consumes the mapping is still running or
stopped early.
"""

from __future__ import annotations

import datetime
from collections import OrderedDict
from pathlib import Path

import yaml

from .mapping_algorithm import (
    DEFAULT_TOLERANCES,
    find_matching_calibration,
    values_match_with_tolerance,
)
from .averaging import value_spread
from .standardized_file_lib import json_safe
from . import _console


PROVENANCE_FILENAME = "calibration_provenance.yaml"

#: Schema of the written file. Bump when a consumer would have to change.
PROVENANCE_SCHEMA_VERSION = "1"

#: Segments the terminal summary names before deferring to the file.
_CONSOLE_SEGMENT_LIMIT = 20

#: Fields compared numerically, and the units to report them in.
_TOLERANCE_FIELDS = OrderedDict([
    ("frequency_start", "Hz"),
    ("frequency_end", "Hz"),
    ("transmit_power", "W"),
    ("transmit_duration_nominal", "s"),
])

#: Fields compared for equality, in the order the matcher applies them.
_EXACT_FIELDS = (
    "transceiver_id",
    "transducer_model",
    "transducer_serial_number",
    "pulse_form",
)

#: How close a failure is to a match. Later means more of the comparison passed.
_STAGE_ORDER = (
    "transceiver_id",
    "transducer_model",
    "transducer_serial_number",
    "pulse_form",
    "frequency_range",
    "transmit_power",
    "transmit_duration_nominal",
)

#: The comparison field behind each matcher step that has one.
_STAGE_FIELDS = {
    "transceiver_id": "transceiver_id",
    "transducer_model": "transducer_model",
    "transducer_serial_number": "transducer_serial_number",
    "pulse_form": "pulse_form",
    "frequency_range": "frequency_start",
    "transmit_power": "transmit_power",
    "transmit_duration_nominal": "transmit_duration_nominal",
}

STATUS_MATCHED = "matched"
STATUS_OVERRIDE = "matched_under_widened_tolerance"
STATUS_UNMATCHED = "unmatched"
STATUS_CONFLICT = "multiple_matches"


class _ProvenanceDumper(yaml.SafeDumper):
    """Block style throughout, so the report reads as a document."""


def _literal_representer(dumper, data):
    """Write a sentence as a literal block rather than wrapping it in quotes."""
    if len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_ProvenanceDumper.add_representer(str, _literal_representer)


def _file_sort_key(config):
    """Order raw file configs by acquisition time, then by name."""
    for field in ("first_ping_time", "metadata_start_time", "last_ping_time"):
        value = config.get(field)
        if value:
            return (0, str(value), config.get("filename") or "")
    return (1, "", config.get("filename") or "")


def _file_times(config):
    """Start and end timestamps for one raw file. Either may be None."""
    start = config.get("first_ping_time") or config.get("metadata_start_time")
    end = config.get("last_ping_time") or start
    return start, end


def _numeric_difference(raw_value, cal_value):
    """Absolute difference of two values, or None if either is not numeric."""
    try:
        return abs(float(raw_value) - float(cal_value))
    except (TypeError, ValueError):
        return None


def _compare_channel(raw_channel, cal_channel, tolerances):
    """Compare a raw channel against a calibration channel, field by field.

    Args:
        raw_channel: Raw channel configuration dict.
        cal_channel: Calibration channel dict, or None.
        tolerances: The effective per-field tolerances.

    Returns:
        Ordered dict of field name to a dict carrying the raw value, the
        calibration value, whether they matched, and for numeric fields the
        difference and the tolerance it was judged against.
    """
    comparison = OrderedDict()
    if cal_channel is None:
        return comparison

    for field in _EXACT_FIELDS:
        raw_value = raw_channel.get(field)
        cal_value = cal_channel.get(field)
        if field == "transducer_serial_number" and (
            raw_value is None or cal_value is None
        ):
            matched = None
        elif field == "pulse_form":
            matched = str(raw_value) == str(cal_value)
        else:
            matched = raw_value == cal_value
        comparison[field] = {
            "raw": raw_value,
            "calibration": cal_value,
            "matched": matched,
        }

    for field, units in _TOLERANCE_FIELDS.items():
        raw_value = raw_channel.get(field)
        cal_value = cal_channel.get(field)
        entry = {
            "raw": raw_value,
            "calibration": cal_value,
            "matched": values_match_with_tolerance(
                raw_value, cal_value, field, tolerances
            ),
            "tolerance": tolerances.get(field),
            "units": units,
        }
        difference = _numeric_difference(raw_value, cal_value)
        if difference:
            entry["difference"] = difference
        if entry["matched"] and not values_match_with_tolerance(
            raw_value, cal_value, field, DEFAULT_TOLERANCES
        ):
            entry["matched_only_under_override"] = True
            entry["default_tolerance"] = DEFAULT_TOLERANCES.get(field)
        comparison[field] = entry

    return comparison


def _unit_suffix(entry):
    """The comparison entry's units, ready to append to a number."""
    units = entry.get("units")
    return f" {units}" if units else ""


def _fmt(value, units=""):
    """Format a value for a sentence without assuming it is a number.

    The report is informational, so a field a raw file never recorded has to
    read as missing rather than stop the run that is describing it.
    """
    if value is None:
        return "not recorded"
    try:
        return f"{float(value):g}{units}"
    except (TypeError, ValueError):
        return f"{value!r}"


def _settings(channel):
    """The fields a mismatch actually turns on, as one compact block."""
    if channel is None:
        return None
    return OrderedDict(
        (field, json_safe(channel.get(field))) for field in _TOLERANCE_FIELDS
    )


def _override_fields(comparison):
    """Names of the fields that matched only because a tolerance was widened."""
    return [
        field
        for field, entry in comparison.items()
        if entry.get("matched_only_under_override")
    ]


def _failure_analysis(raw_channel, calibration_channels, tolerances):
    """Why a raw channel matched nothing, from the candidate that got closest.

    Args:
        raw_channel: The raw channel that matched no calibration.
        calibration_channels: Every loaded calibration channel.
        tolerances: The effective per-field tolerances.

    Returns:
        Tuple of (closest failure detail, its calibration channel, a count of
        how many candidates fell out at each step). The first two are None when
        there were no candidates at all.
    """
    _, _, failure_details, _ = find_matching_calibration(
        raw_channel, calibration_channels, tolerances, verbose=True
    )
    counts = {}
    for detail in failure_details:
        failed_at = detail.get("failed_at")
        counts[failed_at] = counts.get(failed_at, 0) + 1
    if not failure_details:
        return None, None, counts

    def stage_index(detail):
        failed_at = detail.get("failed_at")
        return _STAGE_ORDER.index(failed_at) if failed_at in _STAGE_ORDER else -1

    closest = max(failure_details, key=stage_index)
    cal_channel = next(
        (
            channel
            for channel in calibration_channels
            if channel.get("channel") == closest.get("cal_channel")
        ),
        None,
    )
    return closest, cal_channel, counts


def _outcome(status, unmapped_channels):
    """What the run did with a channel in this state.

    Args:
        status: One of the module's status constants.
        unmapped_channels: The consuming step's declared policy, or None when
            the caller did not say.

    Returns:
        Tuple of (outcome token, sentence explaining it).
    """
    if status == STATUS_MATCHED:
        return "calibration_applied", (
            "The matched calibration was applied. Every compared field is "
            "within its default tolerance."
        )
    if status == STATUS_OVERRIDE:
        return "calibration_applied_under_override", (
            "The matched calibration was applied, but it matched only because "
            "a tolerance was widened. It was measured at a different setting "
            "than it is being applied to, so the gain and sa_correction it "
            "supplies carry a bias of that difference."
        )
    if status == STATUS_CONFLICT:
        return "conflict_unresolved", (
            "Several calibration files matched this channel. No mapping file "
            "is written while a conflict stands."
        )
    if unmapped_channels == "error":
        return "run_stopped", (
            "No calibration matched, and the consuming step runs with "
            "unmapped_channels: error, so the run stopped on this channel."
        )
    if unmapped_channels == "warn":
        return "fallback_to_raw_file_values", (
            "No calibration matched. The consuming step runs with "
            "unmapped_channels: warn, so this channel fell back to the values "
            "the raw file records for it, which is what echopype would "
            "calibrate with given no calibration file at all."
        )
    return "decided_by_consuming_step", (
        "No calibration matched. What happens next is set by the consuming "
        "step's unmapped_channels parameter, which this run did not declare: "
        "warn falls back to the raw file's own recorded values, error stops "
        "the run."
    )


def _channel_status(filename, channel_id, cal_key, comparison, conflict_keys):
    """Classify one file's channel against the mapping result."""
    if (filename, channel_id) in conflict_keys:
        return STATUS_CONFLICT
    if cal_key is None:
        return STATUS_UNMATCHED
    if _override_fields(comparison):
        return STATUS_OVERRIDE
    return STATUS_MATCHED


def _segment_signature(status, cal_key, raw_channel, multiplexing_warning=None):
    """What has to stay the same for files to belong to one segment.

    The raw settings are part of it, so a mid-cruise change of transmit power
    or pulse length starts a new segment even when both sides matched.
    """
    return (
        status,
        cal_key,
        multiplexing_warning,
        tuple(
            (field, json_safe(raw_channel.get(field)))
            for field in _TOLERANCE_FIELDS
        ),
        tuple(
            (field, json_safe(raw_channel.get(field)))
            for field in _EXACT_FIELDS
        ),
    )


def _unmatched_detail(entry, raw_channel, calibration_channels, tolerances):
    """Fill in why nothing matched, on an unmatched segment entry."""
    closest, cal_channel, counts = _failure_analysis(
        raw_channel, calibration_channels, tolerances
    )
    entry["candidates_rejected_at"] = counts
    if closest is None:
        entry["reason"] = "No calibration channels were loaded to compare against."
        return

    failed_at = closest.get("failed_at")
    entry["failed_on"] = failed_at
    entry["closest_calibration"] = closest.get("cal_channel")
    comparison = _compare_channel(raw_channel, cal_channel, tolerances)
    if not comparison:
        # The matcher named a candidate this lookup could not resolve back to
        # its record, so the field is all there is to report.
        entry["reason"] = f"No calibration channel agreed on {failed_at}."
        return
    entry["comparison"] = comparison

    if failed_at == "frequency_range":
        # Either endpoint can be the one that failed, and naming only the start
        # would report a value that matched.
        start = entry["comparison"]["frequency_start"]
        end = entry["comparison"]["frequency_end"]
        entry["reason"] = (
            f"frequency_range differs: these files cover "
            f"{_fmt(start['raw'])} to {_fmt(end['raw'], ' Hz')} and the "
            f"closest calibration covers {_fmt(start['calibration'])} to "
            f"{_fmt(end['calibration'], ' Hz')}."
        )
        return

    failing = entry["comparison"].get(_STAGE_FIELDS.get(failed_at, ""))
    if failing and failing.get("difference") is not None:
        entry["reason"] = (
            f"{failed_at} differs by "
            f"{_fmt(failing['difference'], _unit_suffix(failing))}: these "
            f"files run at {_fmt(failing['raw'], _unit_suffix(failing))} and "
            f"the closest calibration was measured at "
            f"{_fmt(failing['calibration'], _unit_suffix(failing))}, against a "
            f"tolerance of {_fmt(failing['tolerance'], _unit_suffix(failing))}."
        )
    elif failing:
        entry["reason"] = (
            f"{failed_at} differs: the raw files report {failing['raw']!r} and "
            f"the closest calibration reports {failing['calibration']!r}."
        )
    else:
        entry["reason"] = f"No calibration channel agreed on {failed_at}."


def _segment_entry(record, calibration_channels, tolerances, unmapped_channels):
    """Render one contiguous run of files as a provenance segment."""
    raw_channel = record["raw_channel"]
    cal_channel = record["cal_channel"]
    status = record["status"]

    entry = OrderedDict()
    entry["status"] = status
    entry["outcome"] = _outcome(status, unmapped_channels)[0]
    entry["calibration_key"] = record["cal_key"]
    entry["raw_files"] = len(record["filenames"])
    entry["time_start"] = record["time_start"]
    entry["time_end"] = record["time_end"]
    entry["first_file"] = record["filenames"][0]
    entry["last_file"] = record["filenames"][-1]
    entry["raw_settings"] = _settings(raw_channel)
    if record["multiplexing"]:
        entry["multiplexing"] = record["multiplexing"]

    if status == STATUS_UNMATCHED:
        _unmatched_detail(entry, raw_channel, calibration_channels, tolerances)
        return entry

    entry["calibration_settings"] = _settings(cal_channel)
    comparison = _compare_channel(raw_channel, cal_channel, tolerances)
    overrides = _override_fields(comparison)
    if overrides:
        entry["matched_only_under_override"] = overrides
        entry["reason"] = " ".join(
            f"{field} differs by "
            f"{_fmt(comparison[field]['difference'], _unit_suffix(comparison[field]))}"
            f", which the widened tolerance of "
            f"{_fmt(comparison[field]['tolerance'], _unit_suffix(comparison[field]))}"
            f" admits and the default "
            f"{_fmt(comparison[field]['default_tolerance'], _unit_suffix(comparison[field]))}"
            f" would not."
            for field in overrides
        )
        # The settings blocks already carry the values, so only the fields that
        # needed the override are worth spelling out again.
        entry["override_details"] = OrderedDict(
            (field, comparison[field]) for field in overrides
        )
    if record["conflict_keys"]:
        entry["candidate_calibration_keys"] = record["conflict_keys"]
        entry["comparison"] = comparison

    return entry


def _collect_segments(raw_file_configs, result, tolerances):
    """Group every file's channels into contiguous same-behaviour segments.

    Returns:
        Tuple of (segments by channel id, status counts, multiplexed channel
        count, files in time order).
    """
    conflict_keys = {
        (mm.filename, mm.channel_id) for mm in result.multiple_matches
    }
    conflict_candidates = {
        (mm.filename, mm.channel_id): list(mm.matching_cal_keys)
        for mm in result.multiple_matches
    }
    # Multiplexing does not stop a match, so without this the report would call
    # a channel cleanly calibrated while the matcher doubted it.
    multiplexed = {
        (mw.filename, mw.channel_id): mw.warning
        for mw in result.multiplexing_warnings
    }

    ordered = sorted(raw_file_configs, key=_file_sort_key)
    open_segments = {}
    last_seen = {}
    segments = OrderedDict()
    counts = {
        STATUS_MATCHED: 0,
        STATUS_OVERRIDE: 0,
        STATUS_UNMATCHED: 0,
        STATUS_CONFLICT: 0,
    }
    multiplexing_count = 0

    for index, config in enumerate(ordered):
        filename = config.get("filename")
        start, end = _file_times(config)
        file_mapping = result.mapping_dict.get(filename, {})

        for raw_channel in config.get("channels", []):
            channel_id = raw_channel.get("channel_id")
            cal_key = file_mapping.get(channel_id)
            cal_channel = (
                result.calibration_dict.get(cal_key) if cal_key else None
            )
            comparison = _compare_channel(raw_channel, cal_channel, tolerances)
            status = _channel_status(
                filename, channel_id, cal_key, comparison, conflict_keys
            )
            counts[status] += 1

            warning = multiplexed.get((filename, channel_id))
            if warning:
                multiplexing_count += 1
            signature = _segment_signature(status, cal_key, raw_channel, warning)
            current = open_segments.get(channel_id)
            # A channel that skips files was absent from them, so the run ends
            # rather than stretching its time range over data it is not in.
            contiguous = last_seen.get(channel_id) == index - 1
            last_seen[channel_id] = index
            if current is None or not contiguous or current["signature"] != signature:
                current = {
                    "signature": signature,
                    "status": status,
                    "cal_key": cal_key,
                    "cal_channel": cal_channel,
                    "raw_channel": raw_channel,
                    "filenames": [],
                    "time_start": start,
                    "time_end": end,
                    "conflict_keys": conflict_candidates.get(
                        (filename, channel_id), []
                    ),
                    "multiplexing": warning,
                }
                open_segments[channel_id] = current
                segments.setdefault(channel_id, []).append(current)

            current["filenames"].append(filename)
            if start and (not current["time_start"] or start < current["time_start"]):
                current["time_start"] = start
            if end and (not current["time_end"] or end > current["time_end"]):
                current["time_end"] = end

    return segments, counts, multiplexing_count, ordered


def build_calibration_provenance(
    raw_file_configs,
    calibration_data,
    result,
    tolerances,
    requested_tolerances=None,
    unmapped_channels=None,
    cruise_id=None,
):
    """Build the per-channel calibration provenance report.

    Walks every raw file the mapping covered, in acquisition order, and records
    for each channel whether a calibration matched, whether it matched only
    under a widened tolerance, and what the run did about it. Runs of files that
    behaved identically collapse into one segment carrying a time range, so a
    cruise of several thousand files reports as a handful of entries per
    channel.

    Args:
        raw_file_configs: The raw file configurations that were mapped.
        calibration_data: Loaded calibration data with a ``channels`` key.
        result: The MappingResult from
            :func:`mapping_algorithm.build_mapping`.
        tolerances: The effective per-field tolerances the match ran under.
        requested_tolerances: The tolerances the caller asked for, before the
            merge over the defaults. Used to report what was widened.
        unmapped_channels: The consuming step's policy for a channel no
            calibration matched, ``"warn"`` or ``"error"``. When omitted the
            report says the outcome is decided downstream rather than guessing.
        cruise_id: Recorded in the report when known.

    Returns:
        A JSON-safe dict, the same structure written to
        calibration_provenance.yaml.
    """
    calibration_channels = calibration_data.get("channels", [])
    segments, counts, multiplexed, ordered = _collect_segments(
        raw_file_configs, result, tolerances
    )

    widened = OrderedDict()
    for field, value in sorted((requested_tolerances or {}).items()):
        default = DEFAULT_TOLERANCES.get(field)
        if value != default:
            widened[field] = OrderedDict([
                ("default", default),
                ("applied", value),
                ("units", _TOLERANCE_FIELDS.get(field)),
            ])

    report = OrderedDict()
    report["schema_version"] = PROVENANCE_SCHEMA_VERSION
    report["generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if cruise_id is not None:
        report["cruise_id"] = cruise_id

    report["summary"] = OrderedDict([
        ("raw_files", len(ordered)),
        ("time_start", _file_times(ordered[0])[0] if ordered else None),
        ("time_end", _file_times(ordered[-1])[1] if ordered else None),
        ("channels_total", result.total_channels),
        ("channels_matched", counts[STATUS_MATCHED]),
        ("channels_matched_under_override", counts[STATUS_OVERRIDE]),
        ("channels_unmatched", counts[STATUS_UNMATCHED]),
        ("channels_multiple_matches", counts[STATUS_CONFLICT]),
        ("channels_multiplexed", multiplexed),
        ("calibration_files_loaded", result.total_calibrations_loaded),
        ("calibration_files_used", len(result.calibration_dict)),
        ("calibration_files_averaged", len(result.averaged)),
    ])

    report["tolerances"] = OrderedDict([
        ("defaults", dict(DEFAULT_TOLERANCES)),
        ("applied", dict(tolerances)),
        ("overridden", dict(widened)),
    ])

    report["unmatched_channel_policy"] = OrderedDict([
        ("unmapped_channels", unmapped_channels or "not declared to this step"),
        ("effect", _outcome(STATUS_UNMATCHED, unmapped_channels)[1]),
    ])

    # One glossary rather than the same paragraph on every segment.
    present = {
        record["status"]
        for records in segments.values()
        for record in records
    }
    report["outcomes"] = OrderedDict(
        _outcome(status, unmapped_channels)
        for status in (
            STATUS_MATCHED, STATUS_OVERRIDE, STATUS_UNMATCHED, STATUS_CONFLICT
        )
        if status in present
    )

    channels = OrderedDict()
    for channel_id in sorted(segments):
        records = segments[channel_id]
        head = records[0]["raw_channel"]
        channels[channel_id] = OrderedDict([
            ("frequency_hz", json_safe(head.get("frequency"))),
            ("transducer_model", head.get("transducer_model")),
            ("transceiver_id", head.get("transceiver_id")),
            ("segments", [
                _segment_entry(
                    record, calibration_channels, tolerances, unmapped_channels
                )
                for record in records
            ]),
        ])
    report["channels"] = channels

    report["calibration_files"] = OrderedDict(
        (cal_key, _calibration_file_entry(cal_data, result.averaged.get(cal_key)))
        for cal_key, cal_data in sorted(result.calibration_dict.items())
    )

    return json_safe(report)


def _calibration_file_entry(cal_data, sources=None):
    """Describe one calibration file the mapping uses.

    Args:
        cal_data: The calibration record.
        sources: ``{key: record}`` of the calibrations it was averaged from,
            when it is an average made by this run.
    """
    entry = OrderedDict([
        ("channel", cal_data.get("channel")),
        ("calibration_date", cal_data.get("calibration_date")),
        (
            "frequency_hz",
            json_safe(cal_data.get("frequency") or cal_data.get("frequency_start")),
        ),
        ("measured_at", _settings(cal_data)),
        ("source_filenames", cal_data.get("source_filenames")),
        ("is_averaged", bool(cal_data.get("is_averaged"))),
    ])
    if sources:
        records = list(sources.values())
        # Spreads rather than every value: an FM record carries one gain per
        # frequency point, and the largest disagreement is what a reviewer
        # weighs when deciding whether the average was sound.
        entry["gain_correction_spread_db"] = value_spread(records, "gain_correction")
        entry["sa_correction_spread_db"] = value_spread(records, "sa_correction")
        entry["averaged_from"] = [_averaged_source(key, record) for key, record in sources.items()]
    return entry


def _averaged_source(cal_key, record):
    """One calibration that went into an average."""
    source = OrderedDict([
        ("calibration_key", cal_key),
        ("calibration_date", record.get("calibration_date")),
        ("source_filenames", record.get("source_filenames")),
    ])
    # A CW record's corrections are single values, short enough to show.
    for field in ("gain_correction", "sa_correction"):
        values = record.get(field)
        if isinstance(values, list) and len(values) == 1:
            source[field] = values[0]
    return source


def dump_provenance_yaml(report):
    """Render the provenance report as the text of its file.

    Args:
        report: The dict from :func:`build_calibration_provenance`.

    Returns:
        str: The YAML text of the report.
    """
    return yaml.dump(
        report, Dumper=_ProvenanceDumper,
        default_flow_style=False, sort_keys=False, width=88,
    )


def save_calibration_provenance(report, output_dir, filename=None):
    """Write the provenance report next to the mapping files.

    Args:
        report: The dict from :func:`build_calibration_provenance`.
        output_dir: Directory to write into, normally mapping_files/.
        filename: Overrides the default calibration_provenance.yaml.

    Returns:
        Path of the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / (filename or PROVENANCE_FILENAME)
    with open(path, "w") as handle:
        handle.write(dump_provenance_yaml(report))
    return path


def print_provenance_summary(report, path=None):
    """Report anything other than a clean match on the terminal.

    The per-channel detail belongs in the file. This prints only what a run no
    one is watching needs to see, because the step log does not reach a
    terminal.
    """
    summary = report.get("summary", {})
    notable = (
        summary.get("channels_matched_under_override", 0)
        + summary.get("channels_unmatched", 0)
        + summary.get("channels_multiple_matches", 0)
        + summary.get("channels_multiplexed", 0)
    )
    if path is not None:
        _console.console_print(f"\nCalibration provenance written to: {path}")
    if not notable:
        _console.console_print(
            f"  All {summary.get('channels_total', 0)} channel(s) matched a "
            f"calibration within the default tolerances."
        )
        return

    flagged = [
        (channel_id, segment)
        for channel_id, channel in report.get("channels", {}).items()
        for segment in channel.get("segments", [])
        if segment.get("status") != STATUS_MATCHED or segment.get("multiplexing")
    ]
    for channel_id, segment in flagged[:_CONSOLE_SEGMENT_LIMIT]:
        _console.console_print(
            f"  - {channel_id}: {segment.get('outcome')} for "
            f"{segment.get('raw_files')} file(s), "
            f"{segment.get('time_start')} to {segment.get('time_end')}"
        )
        for note in (segment.get("reason"), segment.get("multiplexing")):
            if note:
                _console.console_print(f"    {note}")
    remaining = len(flagged) - _CONSOLE_SEGMENT_LIMIT
    if remaining > 0:
        _console.console_print(
            f"  ... and {remaining} more, in the file above."
        )
