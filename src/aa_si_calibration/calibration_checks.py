"""Warnings about calibration records, as data a caller can present.

Each warning is a dict with ``code``, ``severity`` ("info" or "caution"),
``calibration_key``, ``band_hz`` (``[start, end]`` or None), ``value`` (a
number or None) and ``message``. Nothing here refuses a calibration.
"""

import numpy as np

from . import _console
from .averaging import measured_frequency_bands, merge_coverage, value_spread
from .sphere_model import SPHERE_MATERIALS, sphere_ka, sphere_target_strength


#: A gain difference above this between combined calibrations is flagged. ICES
#: CRR 326 (section 4.1.2.1.2) treats a change this large as a reason to
#: re-evaluate a calibration.
OVERLAP_DIFFERENCE_DB = 0.5

#: Tungsten carbide spheres are most reliable up to this ka, the wavenumber
#: times the sphere radius. Above it their target strength nulls crowd
#: together (Lavery et al. 2017, ICES Journal of Marine Science 74).
MAX_RELIABLE_KA = 16.5

#: An error of this fraction in a sphere's diameter or sound speeds, or in the
#: water sound speed, moves its theoretical target strength curve along the
#: frequency axis by about the same fraction of each frequency.
NULL_SHIFT_FRACTION = 0.005

#: A theoretical target strength that changes by more than this, in dB, under
#: that shift marks a frequency close to one of the sphere's nulls. The change
#: passes into calibrated Sv and TS one for one.
NULL_SENSITIVITY_DB = 0.25


def calibration_warning(code, severity, calibration_key, message, band_hz=None, value=None):
    """One warning in the shape every check returns.

    Args:
        code: Short identifier of the kind of warning.
        severity: "info" or "caution".
        calibration_key: Key of the calibration record it concerns.
        message: The warning in words.
        band_hz: ``[start, end]`` of the frequencies it concerns, if any.
        value: The number that triggered it, if any.

    Returns:
        dict: JSON-safe.
    """
    return {
        "code": code,
        "severity": severity,
        "calibration_key": calibration_key,
        "band_hz": None if band_hz is None else [float(band_hz[0]), float(band_hz[1])],
        "value": None if value is None else float(value),
        "message": message,
    }


def combination_warnings(key, kind, sources):
    """Warnings about a record averaged or merged from several calibrations.

    Args:
        key: The combined record's key.
        kind: "average" or "merge".
        sources: ``{source key: record}`` in the order they were combined.

    Returns:
        list: ``different_spheres`` for an average of different spheres,
        ``overlap_difference`` when the sources' gains differ by more than
        OVERLAP_DIFFERENCE_DB where they overlap, and one ``merge_hole`` for
        each part of a merge's band no source covers.
    """
    records = list(sources.values())
    warnings = []
    if kind == "average" and _spheres_differ(records):
        spheres = "; ".join(dict.fromkeys(sphere_label(r) for r in records))
        warnings.append(calibration_warning(
            "different_spheres", "info", key,
            f"{key} averages calibrations made with different spheres ({spheres}).",
        ))
    spread = value_spread(records, "gain_correction")
    if spread is not None and spread > OVERLAP_DIFFERENCE_DB:
        warnings.append(calibration_warning(
            "overlap_difference", "caution", key,
            f"The calibrations combined into {key} differ by up to {spread:.2f} dB "
            f"in gain where they overlap, more than {OVERLAP_DIFFERENCE_DB} dB. "
            f"At least one of them is likely biased there.",
            value=spread,
        ))
    if kind == "merge":
        for low, high in merge_coverage(records)["holes_hz"]:
            warnings.append(calibration_warning(
                "merge_hole", "caution", key,
                f"{key} has no calibration in {low:.0f}-{high:.0f} Hz. None of the "
                f"merged calibrations has values there. At a ping whose centre "
                f"frequency falls in a gap inside the band echopype interpolates "
                f"across it, and at the edge of the band it gives NaN.",
                band_hz=[low, high],
            ))
    return warnings


def sphere_warnings(key, record):
    """Warnings about one calibration record and the sphere it was made with.

    Args:
        key: The record's calibration key.
        record: A standardized channel dict taken from one calibration.

    Returns:
        list: ``sphere_size`` when the sphere is large for some of the
        record's frequencies; one ``near_null`` for each run of its
        frequencies close to a null in the sphere's theoretical target
        strength; and one ``coverage_gap`` for each part of an FM record's
        band it has no values in. The sphere checks are skipped when the
        diameter or the sound speed is not a recorded number, and
        ``near_null`` also when the material is not one in SPHERE_MATERIALS.
    """
    values = record.get("frequency")
    if not isinstance(values, (list, tuple)):
        values = [values]
    frequency = np.array(
        [f for f in (_number(v) for v in values) if f is not None], dtype=float
    )
    warnings = []
    diameter = _number(record.get("sphere_diameter"))
    sound_speed = _number(record.get("sound_speed_indicative"))
    if frequency.size and diameter and sound_speed:
        ka = sphere_ka(frequency, diameter, sound_speed)
        large = frequency[ka > MAX_RELIABLE_KA]
        if large.size:
            warnings.append(calibration_warning(
                "sphere_size", "caution", key,
                f"{key} was calibrated with a {diameter:g} mm sphere, which is "
                f"large for {large.min():.0f}-{large.max():.0f} Hz (ka up to "
                f"{ka.max():.1f}, above {MAX_RELIABLE_KA}). Sphere target strength "
                f"nulls are closely spaced there, so the calibration is less "
                f"reliable.",
                band_hz=[large.min(), large.max()],
                value=round(float(ka.max()), 2),
            ))
        material = str(record.get("sphere_material") or "").strip().lower()
        if material in SPHERE_MATERIALS:
            warnings.extend(_near_null_warnings(
                key, frequency, diameter, sound_speed, material,
            ))
    if frequency.size > 1:
        for low, high in merge_coverage([record])["holes_hz"]:
            warnings.append(calibration_warning(
                "coverage_gap", "info", key,
                f"{key} has no values in {low:.0f}-{high:.0f} Hz.",
                band_hz=[low, high],
            ))
    return warnings


def print_warnings(warnings):
    """Print warnings, cautions to the terminal and the rest to the run log.

    Inside a recipe step an ordinary print reaches only the log, which keeps
    the terminal to what a user has to weigh.
    """
    for warning in warnings:
        if warning["severity"] == "caution":
            _console.console_print(f"WARNING: {warning['message']}")
        else:
            print(f"NOTE: {warning['message']}")


def null_sensitivity(frequency, diameter, sound_speed, material):
    """How much a sphere's theoretical target strength changes under a small shift.

    The larger change from each frequency to NULL_SHIFT_FRACTION of it either
    side, in dB. Taken to both sides, because at the bottom of a null the
    change is steep either way but the centred difference is near zero.

    Args:
        frequency: Frequencies in Hz.
        diameter: Sphere diameter in mm.
        sound_speed: Water sound speed in m s-1.
        material: A key of SPHERE_MATERIALS.

    Returns:
        np.ndarray: One change per frequency.
    """
    frequency = np.asarray(frequency, dtype=float)
    step = NULL_SHIFT_FRACTION * frequency
    ts = sphere_target_strength(
        np.concatenate([frequency - step, frequency, frequency + step]),
        diameter, sound_speed, material,
    ).reshape(3, -1)
    return np.maximum(np.abs(ts[0] - ts[1]), np.abs(ts[2] - ts[1]))


def _near_null_warnings(key, frequency, diameter, sound_speed, material):
    """One ``near_null`` warning per run of a record's frequencies close to a null."""
    change = null_sensitivity(frequency, diameter, sound_speed, material)
    flagged = frequency[change > NULL_SENSITIVITY_DB]
    warnings = []
    for low, high in _runs(flagged, frequency):
        inside = (frequency >= low) & (frequency <= high)
        largest = float(change[inside].max())
        span = f"{low:.0f} Hz" if low == high else f"{low:.0f}-{high:.0f} Hz"
        warnings.append(calibration_warning(
            "near_null", "caution", key,
            f"{key} was calibrated with a {diameter:g} mm {material} sphere close "
            f"to one of its target strength nulls at {span}: an error of "
            f"{NULL_SHIFT_FRACTION:.1%} in the sphere's size or sound speeds "
            f"changes its theoretical target strength by up to {largest:.2f} dB "
            f"there, and the calibration with it.",
            band_hz=[low, high],
            value=round(largest, 2),
        ))
    return warnings


def _runs(flagged, frequency):
    """Runs of flagged frequencies with no unflagged point or gap between."""
    if not flagged.size:
        return []
    points = np.unique(frequency)
    position = np.searchsorted(points, np.unique(flagged))
    band_ends = [high for _, high in measured_frequency_bands(points)]
    band = np.searchsorted(band_ends, points[position])
    breaks = np.flatnonzero((np.diff(position) > 1) | (np.diff(band) != 0))
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [position.size - 1]))
    return [
        [float(points[position[s]]), float(points[position[e]])]
        for s, e in zip(starts, ends)
    ]


def _spheres_differ(records):
    """Whether the records name more than one sphere diameter or material."""
    return any(
        len({r.get(field) for r in records if r.get(field) is not None}) > 1
        for field in ("sphere_diameter", "sphere_material")
    )


def sphere_label(record):
    """A record's sphere in words, such as "38.1 mm tungsten carbide".

    Args:
        record: A standardized channel dict.

    Returns:
        str: The diameter and material it records, or "unknown sphere".
    """
    diameter = _number(record.get("sphere_diameter"))
    parts = [
        f"{diameter:g} mm" if diameter is not None else None,
        str(record.get("sphere_material") or "") or None,
    ]
    return " ".join(p for p in parts if p) or "unknown sphere"


def _number(value):
    """*value* as a finite float, or None when it is not a recorded number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    value = float(value)
    return value if np.isfinite(value) else None
