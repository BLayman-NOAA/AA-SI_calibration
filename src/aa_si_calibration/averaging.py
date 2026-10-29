"""Average or merge several standardized calibration records into one.

When more than one calibration matches a raw channel, a user can choose to
combine them instead of keeping one.

An average is for repeat calibrations of the same transducer, at the same
settings and with the same sphere, such as one before and one after a cruise.
A merge is the EK80 software's way of combining calibrations made with
different spheres: the calibrations are taken in the order given, the first is
used wherever it is valid, and each later one fills only the frequencies the
earlier ones leave uncovered. Frequencies none of them covers stay uncovered.

A calibration only has values where it is valid. For an FM record that is its
``valid_frequency_bands``, within the span of its frequency points, so neither
mode interpolates a calibration across the inhibited band around a sphere's
target strength null.
"""

import datetime

import jsonschema
import numpy as np

from .constants import DEFAULT_TOLERANCES
from .standardized_file_lib import (
    drop_unset_optional_fields,
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

#: The setting fields a merge lets differ: merging is how different spheres
#: are combined.
SPHERE_FIELDS = (
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
    "valid_frequency_bands",
    "is_averaged",
    "is_merged",
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
    only within the bands where it is valid, without extrapolating or bridging
    its own nulls, following pyEchoLab's get_calibration_from_xml.

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
            average or a merge, a field in MATCHED_FIELDS or a CW frequency
            differs, or the result is not a valid standardized record.
    """
    return _combine(records, merge=False, record_author=record_author)


def merge_calibration_records(records, record_author=None):
    """Merge FM calibration records of one channel, as the EK80 software does.

    The records are taken in the order given. At each frequency the first
    record that is valid there supplies every per-frequency value, and the
    later records fill only what the earlier ones leave uncovered. The merged
    record holds only measured points, never interpolated ones, and a value
    the supplying record leaves null at a point stays null. Values with
    one entry per record, such as the equivalent beam angle and the
    environment, come from the first record that has them. Nothing is
    averaged. The sphere may differ between records; every other setting must
    match.

    Args:
        records: Two or more standardized FM channel dicts, in priority order.
            One may be an average. A ``_calibration_file_key`` on each names
            it in error messages.
        record_author: Recorded as the author of the new record. When None,
            the sources' author is kept if they share one.

    Returns:
        dict: A new standardized channel record with ``is_merged`` set,
        validated against the schema. Use :func:`merge_coverage` for the
        bands each record supplied and the frequencies none covers.

    Raises:
        ValueError: If fewer than two records are given, one is itself a
            merge, the records are CW, a field in MATCHED_FIELDS other than
            the sphere differs, or the result is not a valid standardized
            record.
    """
    return _combine(records, merge=True, record_author=record_author)


def calibration_coverage(record):
    """Frequency intervals where a calibration record has values.

    Each of the record's valid bands that holds at least one of its frequency
    points, clipped to the span from its lowest to its highest point. A record
    without valid bands covers that whole span. Within an interval the record
    has values only between its own first and last point there.

    Args:
        record: A standardized channel dict.

    Returns:
        list: Sorted, non-overlapping ``[start, end]`` pairs in Hz. Empty when
        the record has no frequency.
    """
    freq = _numbers(record.get("frequency"))
    freq = freq[np.isfinite(freq)]
    if not freq.size:
        return []
    low, high = float(freq.min()), float(freq.max())
    bands = record.get("valid_frequency_bands")
    if not bands:
        return [[low, high]]
    intervals = [
        [max(float(start), low), min(float(end), high)]
        for start, end in bands
        if np.any((freq >= start) & (freq <= end))
    ]
    return _union(intervals)


def merge_coverage(records):
    """Which record supplies each part of a merge's band, and what none covers.

    The band is the records' shared ``frequency_start`` to ``frequency_end``,
    or the span of their coverage when that is not recorded.

    Args:
        records: The standardized channel dicts of a merge, in priority order.

    Returns:
        dict: ``coverage``, a list of ``{"band_hz": [start, end], "source":
        name}`` sorted by frequency, and ``holes_hz``, the ``[start, end]``
        intervals no record covers.
    """
    intervals = [calibration_coverage(r) for r in records]
    start = records[0].get("frequency_start")
    end = records[0].get("frequency_end")
    if start is None or end is None:
        flat = [i for per_record in intervals for i in per_record]
        if not flat:
            return {"coverage": [], "holes_hz": []}
        start, end = min(i[0] for i in flat), max(i[1] for i in flat)
    remaining = [[float(start), float(end)]]
    coverage = []
    for record, per_record in zip(records, intervals):
        for interval in per_record:
            coverage.extend(
                {"band_hz": part, "source": _label(record)}
                for part in _intersect(remaining, interval)
            )
            remaining = _subtract(remaining, interval)
    coverage.sort(key=lambda entry: entry["band_hz"][0])
    return {"coverage": coverage, "holes_hz": remaining}


def value_spread(records, field):
    """Largest difference in a field between calibration records.

    Taken at whichever frequency the records disagree most, over the points at
    least two of them cover. In the field's own units, so dB for gain.

    Args:
        records: The standardized channel dicts that were combined.
        field: A numeric field name.

    Returns:
        float | None: The spread, or None when fewer than two records have the
        field at any common point.
    """
    axes = _frequency_axes(records, merge=False)
    rows = _aligned(records, field, axes)
    if rows is None:
        return None
    shared = np.sum(np.isfinite(rows), axis=0) >= 2
    if not shared.any():
        return None
    rows = rows[:, shared]
    return round(float(np.max(np.nanmax(rows, axis=0) - np.nanmin(rows, axis=0))), 4)


def _combine(records, merge, record_author):
    """Average or merge records into one validated standardized record."""
    verb = "merge" if merge else "average"
    if len(records) < 2:
        raise ValueError(
            f"{'Merging' if merge else 'Averaging'} needs at least two calibration records."
        )

    sources = [ensure_string_identifiers(dict(r)) for r in records]
    for source in sources:
        source["calibration_date"] = normalize_calibration_date(
            source.get("calibration_date")
        )
        if source.get("is_merged"):
            raise ValueError(
                f"Cannot {verb} {_label(source)}: it is already a merge. "
                f"{verb.capitalize()} the calibrations it was made from instead."
            )
        if not merge and source.get("is_averaged"):
            raise ValueError(
                f"Cannot average {_label(source)}: it is already an average. "
                f"Average the calibrations it was made from instead."
            )
    if not merge:
        sources.sort(key=lambda s: s["calibration_date"] or [])
    matched = [f for f in MATCHED_FIELDS if not (merge and f in SPHERE_FIELDS)]
    for field in matched:
        _require_same(sources, field, null_differs=field in SETTING_FIELDS, merge=merge)

    axes = _frequency_axes(sources, merge=merge)
    if axes[1] is None:
        if merge:
            names = ", ".join(_label(s) for s in sources)
            raise ValueError(
                f"Cannot merge these calibrations: merging is for FM calibrations "
                f"with several frequency points, and {names} are CW. Select one "
                f"of them instead."
            )
        _require_same(sources, "frequency", null_differs=True, merge=merge)

    schema = load_standardized_calibration_schema()
    precisions = extract_channel_precision_map(schema)

    record = get_empty_channel_params()
    for field in matched:
        record[field] = next(
            (s[field] for s in sources if s.get(field) is not None), None
        )
    grid = axes[1]
    record["frequency"] = (
        sources[0].get("frequency") if grid is None
        else _rounded(grid, precisions.get("frequency"))
    )
    for field in DECIBEL_FIELDS + LINEAR_FIELDS:
        measured = _measured_value(sources, field, axes) if merge else None
        record[field] = measured if measured is not None else _combined_value(
            sources, field, axes,
            reduce=_first if merge else _mean,
            decibel=field in DECIBEL_FIELDS and not merge,
            precision=precisions.get(field),
        )
    for field in COMBINED_LIST_FIELDS:
        record[field] = _combined(s.get(field) for s in sources)
    for field in TEXT_FIELDS:
        record[field] = _joined(s.get(field) for s in sources)
    if merge:
        diameters = _distinct(s.get("sphere_diameter") for s in sources)
        record["sphere_diameter"] = diameters[0] if len(diameters) == 1 else None
        record["sphere_material"] = _joined(s.get("sphere_material") for s in sources)
    if grid is not None and any(s.get("valid_frequency_bands") for s in sources):
        band_precision = precisions.get("valid_frequency_bands")
        record["valid_frequency_bands"] = [
            _rounded(interval, band_precision)
            for interval in _union([i for c in axes[2] for i in c])
        ]

    authors = _distinct(s.get("record_author") for s in sources)
    record["record_author"] = (
        record_author if record_author is not None
        else authors[0] if len(authors) == 1 else None
    )
    record["record_created"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record["is_averaged"] = not merge or any(s.get("is_averaged") for s in sources)
    record["is_merged"] = merge
    drop_unset_optional_fields(record)

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
            f"Cannot {verb} these calibrations: the result is not a valid "
            f"standardized record. {err.message}"
        ) from err
    return record


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


def _require_same(sources, field, null_differs, merge=False):
    """Raise unless every source has the same value for *field*.

    Args:
        sources: The records being combined.
        field: The field to compare.
        null_differs: If True a null against a value is a difference. If False
            nulls are left out of the comparison.
        merge: Whether the records are being merged rather than averaged,
            which only changes the message.
    """
    values = [s.get(field) for s in sources]
    if not null_differs:
        values = [v for v in values if v is not None]
    if all(_same(field, values[0], v) for v in values[1:]):
        return
    values = ", ".join(f"{_label(s)}: {s.get(field)!r}" for s in sources)
    if merge:
        raise ValueError(
            f"Cannot merge these calibrations: {field} differs ({values}). "
            f"Only calibrations of the same transducer at the same settings are "
            f"merged; the sphere may differ."
        )
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


def _frequency_axes(sources, merge):
    """Each source's frequency points and coverage, and the grid they go on.

    For an average the grid is every point a source covers. For a merge it is
    each source's covered points that no earlier source covers, so every point
    of the merged record is one its supplier measured.

    Returns:
        tuple: ``(freqs, grid, coverage, owners)``. ``grid``, ``coverage`` and
        ``owners`` are None for CW records; otherwise ``coverage`` is each
        source's :func:`calibration_coverage`. For a merge ``owners`` gives,
        for each grid point, the index of the source that measured it; for an
        average it is None.

    Raises:
        ValueError: If a source has no frequency, or none of its points lies
            in its valid bands.
    """
    freqs = [_numbers(s.get("frequency")) for s in sources]
    if all(f.size <= 1 for f in freqs):
        return freqs, None, None, None
    if any(f.size == 0 for f in freqs):
        missing = ", ".join(_label(s) for s, f in zip(sources, freqs) if f.size == 0)
        raise ValueError(
            f"Cannot combine these calibrations: frequency is missing from {missing}."
        )
    coverage = [calibration_coverage(s) for s in sources]
    empty = ", ".join(_label(s) for s, c in zip(sources, coverage) if not c)
    if empty:
        raise ValueError(
            f"Cannot combine these calibrations: no frequency point of {empty} "
            f"lies inside its valid_frequency_bands."
        )
    points, owners = [], []
    for index, (freq, own) in enumerate(zip(freqs, coverage)):
        keep = _inside(freq, own)
        if merge:
            for earlier in coverage[:index]:
                keep &= ~_inside(freq, earlier)
        points.append(freq[keep])
        owners.append(np.full(int(keep.sum()), index))
    grid, first = np.unique(np.concatenate(points), return_index=True)
    return freqs, grid, coverage, np.concatenate(owners)[first] if merge else None


def _inside(freq, intervals):
    """Which frequencies fall in any of *intervals*, ends included."""
    mask = np.zeros(freq.shape, dtype=bool)
    for low, high in intervals:
        mask |= (freq >= low) & (freq <= high)
    return mask


def _onto_grid(freq, values, grid, coverage):
    """Interpolate one source onto the grid, only where the source is valid.

    Each covered interval is interpolated from that interval's own points, so
    a value is never carried across a gap in the source. NaN outside the
    intervals, past the first or last point of an interval, and between any
    two points where either is null.
    """
    out = np.full(grid.size, np.nan)
    for low, high in coverage:
        inside = (freq >= low) & (freq <= high)
        if inside.any():
            part = _interpolate(freq[inside], values[inside], grid)
            out = np.where(np.isnan(out), part, out)
    return out


def _interpolate(freq, values, grid):
    """Interpolate points onto the grid without extrapolating or bridging nulls.

    A null means the source has no value there, so its neighbours are not
    stretched across the gap.
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


def _aligned(sources, field, axes):
    """One row per source of a field's values, lined up point for point.

    A per-frequency FM field is interpolated onto the grid within each
    source's coverage. Anything else is lined up element by element, which
    needs the same number of values in every source that has the field.

    Returns:
        np.ndarray | None: Shape ``(sources, points)`` with NaN where a source
        has no value, or None when no source has the field.
    """
    freqs, grid, coverage, _ = axes
    values = [_numbers(s.get(field)) for s in sources]
    present = [v for v in values if v.size]
    if not present:
        return None
    if grid is not None and all(v.size in (0, f.size) for v, f in zip(values, freqs)):
        return np.vstack([
            _onto_grid(f, v, grid, c) if v.size else np.full(grid.size, np.nan)
            for v, f, c in zip(values, freqs, coverage)
        ])
    width = present[0].size
    if any(v.size not in (0, width) for v in values):
        sizes = ", ".join(f"{_label(s)}: {v.size}" for s, v in zip(sources, values))
        raise ValueError(
            f"Cannot combine these calibrations: {field} has a different number "
            f"of values in each ({sizes}), so they cannot be lined up."
        )
    return np.vstack([v if v.size else np.full(width, np.nan) for v in values])


def _measured_value(sources, field, axes):
    """A per-frequency field of a merge, from whichever source measured each point.

    Every field at a point comes from the one source that supplies that point,
    and is null where that source is null there, so nothing is interpolated
    and no point mixes values from two sources.

    Returns:
        list | None: One value per grid point, or None when the field is not
        held per frequency point by every source that has it.
    """
    freqs, grid, _, owners = axes
    if grid is None:
        return None
    values = [_numbers(s.get(field)) for s in sources]
    if not any(v.size for v in values) or any(
        v.size not in (0, f.size) for v, f in zip(values, freqs)
    ):
        return None
    merged = np.full(grid.size, np.nan)
    for index, (point, owner) in enumerate(zip(grid, owners)):
        if values[owner].size:
            merged[index] = values[owner][np.flatnonzero(freqs[owner] == point)[0]]
    return _rounded(merged, None)


def _mean(rows):
    """The equal-weight mean of each column, skipping NaN."""
    count = np.sum(np.isfinite(rows), axis=0)
    return np.divide(
        np.nansum(rows, axis=0), count,
        out=np.full(rows.shape[1], np.nan), where=count > 0,
    )


def _first(rows):
    """The first finite value of each column, in row order."""
    finite = np.isfinite(rows)
    picked = rows[np.argmax(finite, axis=0), np.arange(rows.shape[1])]
    return np.where(finite.any(axis=0), picked, np.nan)


def _combined_value(sources, field, axes, reduce, decibel, precision):
    """A numeric field combined across sources by *reduce*, skipping nulls."""
    rows = _aligned(sources, field, axes)
    if rows is None:
        return None
    if decibel:
        rows = 10 ** (rows / 10)
    combined = reduce(rows)
    if decibel:
        combined = 10 * np.log10(combined)
    rounded = _rounded(combined, precision)
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


def _union(intervals):
    """Sorted, merged ``[start, end]`` intervals."""
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    return merged


def _intersect(intervals, interval):
    """The parts of *intervals* inside *interval*, dropping empty ones."""
    low, high = interval
    parts = [[max(a, low), min(b, high)] for a, b in intervals]
    return [p for p in parts if p[0] < p[1]]


def _subtract(intervals, interval):
    """*intervals* with *interval* removed, dropping empty pieces."""
    low, high = interval
    out = []
    for a, b in intervals:
        if a < low:
            out.append([a, min(b, low)])
        if b > high:
            out.append([max(a, high), b])
    return [p for p in out if p[0] < p[1]]


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
