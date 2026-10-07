"""Average several standardized calibration records into one.

When more than one calibration matches a raw channel, a user can choose their
average instead of one of them. Only calibrations of the same transducer, at
the same settings and with the same sphere, are combined; anything else raises.
"""

import datetime

import jsonschema
import numpy as np

from .constants import DEFAULT_TOLERANCES
from .standardized_file_lib import (
    enforce_precision_limits,
    ensure_string_identifiers,
    extract_channel_precision_map,
    get_empty_channel_params,
    load_standardized_calibration_schema,
    normalize_calibration_date,
    round_numeric_value,
)


#: The settings a gain applies to, and the sphere it was measured with. Every
#: averaged calibration must share them, and a null against a value is a
#: difference: a gain measured at an unknown setting cannot be vouched for.
SETTING_FIELDS = (
    "channel",
    "pulse_form",
    "frequency_start",
    "frequency_end",
    "nominal_transducer_frequency",
    "transmit_power",
    "transmit_duration_nominal",
    "sample_interval",
    "transmit_bandwidth",
    "sphere_diameter",
    "sphere_material",
)

#: What identifies the hardware and the file. Sources must not disagree, but a
#: null is taken as not recorded, as the matcher treats a missing serial number,
#: and the average carries the value the other sources give.
IDENTITY_FIELDS = (
    "transceiver_id",
    "transceiver_model",
    "transceiver_ethernet_address",
    "transceiver_serial_number",
    "transceiver_number",
    "transceiver_port",
    "channel_instance_number",
    "transducer_model",
    "transducer_serial_number",
    "beam_type",
    "multiplexing_found",
    "source_file_type",
)

#: Fields every averaged calibration must share. A gain measured with any of
#: them different is a measurement of something else.
MATCHED_FIELDS = SETTING_FIELDS + IDENTITY_FIELDS

#: Logarithmic quantities, averaged as the linear values they stand for.
DECIBEL_FIELDS = (
    "gain_correction",
    "sa_correction",
    "equivalent_beam_angle",
)

#: Linear quantities, averaged as they are.
LINEAR_FIELDS = (
    "beamwidth_transmit_major",
    "beamwidth_receive_major",
    "beamwidth_transmit_minor",
    "beamwidth_receive_minor",
    "echoangle_major",
    "echoangle_minor",
    "echoangle_major_sensitivity",
    "echoangle_minor_sensitivity",
    "absorption_indicative",
    "sound_speed_indicative",
    "temperature",
    "salinity",
    "acidity",
    "pressure",
)

#: Lists that carry the entries of every source.
COMBINED_LIST_FIELDS = (
    "calibration_date",
    "source_filenames",
    "source_file_paths",
)

#: Free text, kept when the sources agree and joined when they do not.
TEXT_FIELDS = (
    "calibration_comments",
    "calibration_version",
    "calibration_acquisition_method",
    "source_file_location",
    "sonar_software_version",
    "sonar_software_name",
)

#: Set on the new record rather than taken from the sources.
GENERATED_FIELDS = (
    "frequency",
    "is_averaged",
    "record_created",
    "record_author",
)

TEXT_SEPARATOR = "; "


def average_calibration_records(records, record_author=None):
    """Average standardized calibration records of one channel into a new record.

    Gain, Sa correction and the equivalent beam angle are averaged in the
    linear domain. Beam widths, angle offsets, angle sensitivities and the
    environment are averaged as they are. Every source counts equally, and a
    null in one source is skipped rather than counted. FM records are averaged
    over the union of their frequency points, each source interpolated onto it
    without extrapolating or bridging its own nulls, following pyEchoLab's
    get_calibration_from_xml.

    Args:
        records: Two or more standardized channel dicts. A
            ``_calibration_file_key`` on each names it in error messages.
        record_author: Recorded as the author of the new record. When None,
            the sources' author is kept if they share one.

    Returns:
        dict: A new standardized channel record with ``is_averaged`` set,
        validated against the schema.

    Raises:
        ValueError: If fewer than two records are given, one is itself an
            average, a field in MATCHED_FIELDS or a CW frequency differs, or
            the result is not a valid standardized record.
    """
    if len(records) < 2:
        raise ValueError("Averaging needs at least two calibration records.")

    sources = [ensure_string_identifiers(dict(r)) for r in records]
    for source in sources:
        source["calibration_date"] = normalize_calibration_date(
            source.get("calibration_date")
        )
        if source.get("is_averaged"):
            raise ValueError(
                f"Cannot average {_label(source)}: it is already an average. "
                f"Average the calibrations it was made from instead."
            )
    sources.sort(key=lambda s: s["calibration_date"] or [])
    for field in MATCHED_FIELDS:
        _require_same(sources, field, null_differs=field in SETTING_FIELDS)

    freqs, grid = _frequency_axes(sources)
    if grid is None:
        _require_same(sources, "frequency", null_differs=True)

    schema = load_standardized_calibration_schema()
    precisions = extract_channel_precision_map(schema)

    record = get_empty_channel_params()
    for field in MATCHED_FIELDS:
        record[field] = next(
            (s[field] for s in sources if s.get(field) is not None), None
        )
    record["frequency"] = (
        sources[0].get("frequency") if grid is None
        else _rounded(grid, precisions.get("frequency"))
    )
    for field in DECIBEL_FIELDS + LINEAR_FIELDS:
        record[field] = _mean(
            sources, field, freqs, grid,
            decibel=field in DECIBEL_FIELDS,
            precision=precisions.get(field),
        )
    for field in COMBINED_LIST_FIELDS:
        record[field] = _combined(s.get(field) for s in sources)
    for field in TEXT_FIELDS:
        record[field] = _joined(s.get(field) for s in sources)

    authors = _distinct(s.get("record_author") for s in sources)
    record["record_author"] = (
        record_author if record_author is not None
        else authors[0] if len(authors) == 1 else None
    )
    record["record_created"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record["is_averaged"] = True

    # Several schema fields may be absent but not null, so a field every source
    # leaves out stays out rather than being written as null.
    record = {
        field: value for field, value in record.items()
        if value is not None or field in GENERATED_FIELDS
        or any(field in s for s in sources)
    }
    # Source files are not validated when they are read, so a bad value in one
    # only surfaces here. Raised as the same error type as any other refusal.
    try:
        jsonschema.validate(instance=record, schema=schema)
        enforce_precision_limits(record, precisions)
    except jsonschema.ValidationError as err:
        raise ValueError(
            f"Cannot average these calibrations: the result is not a valid "
            f"standardized record. {err.message}"
        ) from err
    return record


def value_spread(records, field):
    """Largest difference in a field between calibration records.

    Taken at whichever frequency the records disagree most, over the points at
    least two of them cover. In the field's own units, so dB for gain.

    Args:
        records: The standardized channel dicts that were averaged.
        field: A numeric field name.

    Returns:
        float | None: The spread, or None when fewer than two records have the
        field at any common point.
    """
    freqs, grid = _frequency_axes(records)
    rows = _aligned(records, field, freqs, grid)
    if rows is None:
        return None
    shared = np.sum(np.isfinite(rows), axis=0) >= 2
    if not shared.any():
        return None
    rows = rows[:, shared]
    return round(float(np.max(np.nanmax(rows, axis=0) - np.nanmin(rows, axis=0))), 4)


def _label(record):
    """How a source record is named in an error message."""
    return (
        record.get("_calibration_file_key")
        or ", ".join(record.get("source_filenames") or [])
        or "an unnamed record"
    )


def _same(field, a, b):
    """Whether two values of a matched field count as the same setting."""
    tolerance = DEFAULT_TOLERANCES.get(field)
    if tolerance is None or a is None or b is None:
        return a == b
    a, b = _numbers(a), _numbers(b)
    return a.shape == b.shape and bool(
        np.all(np.isclose(a, b, rtol=0, atol=tolerance, equal_nan=True))
    )


def _require_same(sources, field, null_differs):
    """Raise unless every source has the same value for *field*.

    Args:
        sources: The records being averaged.
        field: The field to compare.
        null_differs: If True a null against a value is a difference. If False
            nulls are left out of the comparison.
    """
    values = [s.get(field) for s in sources]
    if not null_differs:
        values = [v for v in values if v is not None]
    if all(_same(field, values[0], v) for v in values[1:]):
        return
    values = ", ".join(f"{_label(s)}: {s.get(field)!r}" for s in sources)
    raise ValueError(
        f"Cannot average these calibrations: {field} differs ({values}). "
        f"Only calibrations of the same transducer, at the same settings and "
        f"with the same sphere, are averaged."
    )


def _numbers(value):
    """A value or list of values as a float array, with null as NaN."""
    if value is None:
        return np.empty(0)
    items = value if isinstance(value, (list, tuple, np.ndarray)) else [value]
    return np.array([np.nan if v is None else v for v in items], dtype=float)


def _frequency_axes(sources):
    """Each source's frequency points, and the grid an FM average is put on.

    Returns:
        tuple: ``(freqs, grid)``. ``grid`` is None for CW records and the sorted
        union of every source's points for FM.
    """
    freqs = [_numbers(s.get("frequency")) for s in sources]
    if all(f.size <= 1 for f in freqs):
        return freqs, None
    if any(f.size == 0 for f in freqs):
        missing = ", ".join(_label(s) for s, f in zip(sources, freqs) if f.size == 0)
        raise ValueError(
            f"Cannot average these calibrations: frequency is missing from {missing}."
        )
    return freqs, np.unique(np.concatenate(freqs))


def _onto_grid(freq, values, grid):
    """Interpolate one source onto the grid.

    NaN outside the band the source covers, and between any two of its own
    points where either is null: a null means the source has no value there,
    so its neighbours are not stretched across the gap.
    """
    known = np.isfinite(freq)
    if not known.any():
        return np.full(grid.size, np.nan)
    order = np.argsort(freq[known])
    freq, values = freq[known][order], values[known][order]
    upper = np.clip(np.searchsorted(freq, grid), 1, max(freq.size - 1, 1))
    bridged = np.interp(grid, freq, np.nan_to_num(values), left=np.nan, right=np.nan)
    if freq.size > 1:
        bridged[np.isnan(values[upper - 1]) | np.isnan(values[upper])] = np.nan
    # A grid point that is one of the source's own keeps that point's value,
    # whatever its neighbours are.
    own = np.isin(grid, freq)
    bridged[own] = values[np.searchsorted(freq, grid[own])]
    return bridged


def _aligned(sources, field, freqs, grid):
    """One row per source of a field's values, lined up point for point.

    A per-frequency FM field is interpolated onto *grid*. Anything else is
    lined up element by element, which needs the same number of values in
    every source that has the field.

    Returns:
        np.ndarray | None: Shape ``(sources, points)`` with NaN where a source
        has no value, or None when no source has the field.
    """
    values = [_numbers(s.get(field)) for s in sources]
    present = [v for v in values if v.size]
    if not present:
        return None
    if grid is not None and all(v.size in (0, f.size) for v, f in zip(values, freqs)):
        return np.vstack([
            _onto_grid(f, v, grid) if v.size else np.full(grid.size, np.nan)
            for v, f in zip(values, freqs)
        ])
    width = present[0].size
    if any(v.size not in (0, width) for v in values):
        sizes = ", ".join(f"{_label(s)}: {v.size}" for s, v in zip(sources, values))
        raise ValueError(
            f"Cannot average these calibrations: {field} has a different number "
            f"of values in each ({sizes}), so they cannot be lined up."
        )
    return np.vstack([v if v.size else np.full(width, np.nan) for v in values])


def _mean(sources, field, freqs, grid, decibel, precision):
    """The equal-weight mean of a numeric field, skipping nulls."""
    rows = _aligned(sources, field, freqs, grid)
    if rows is None:
        return None
    if decibel:
        rows = 10 ** (rows / 10)
    count = np.sum(np.isfinite(rows), axis=0)
    mean = np.divide(
        np.nansum(rows, axis=0), count,
        out=np.full(rows.shape[1], np.nan), where=count > 0,
    )
    if decibel:
        mean = 10 * np.log10(mean)
    rounded = _rounded(mean, precision)
    if any(isinstance(s.get(field), (list, tuple)) for s in sources):
        return rounded
    return rounded[0]


def _rounded(values, precision):
    """Plain floats at the schema precision, with NaN as null."""
    return [
        None if not np.isfinite(v)
        else round_numeric_value(float(v), precision) if precision is not None
        else float(v)
        for v in values
    ]


def _distinct(values):
    """Non-null values in first-seen order, without repeats."""
    seen = []
    for value in values:
        if value is not None and value not in seen:
            seen.append(value)
    return seen


def _combined(lists):
    """Every entry of several lists, in order, without repeats; None if empty."""
    return _distinct(item for items in lists for item in (items or [])) or None


def _joined(values):
    """The shared value of a text field, or the distinct values joined."""
    distinct = _distinct(values)
    if not distinct:
        return None
    return TEXT_SEPARATOR.join(str(v) for v in distinct)
