"""Calibration key generation, filename mapping, and channel identification.

Provides the canonical ``build_calibration_key`` function that generates
unique identifiers for channel configurations, plus helpers for mapping
those keys to short filenames and extracting channel components from
channel name strings.
"""

import numpy as np

from .constants import (
    SERIAL_NUMBER_PATTERN,
    TRANSDUCER_SERIAL_UNKNOWN,
)
from .utils import extract_nominal_frequency_from_transducer_model


# Schema-derived precisions for the numeric fields used in the calibration key.
_KEY_FIELD_PRECISIONS = {
    'transmit_duration_nominal': 6,
    'transmit_power': 10,
    'frequency_start': 10,
    'frequency_end': 10,
}


def _round_key_field(field_name, channel_data):
    """Round a numeric field to its schema precision for use in calibration keys."""
    value = channel_data.get(field_name)
    if value is None:
        return ''
    precision = _KEY_FIELD_PRECISIONS.get(field_name)
    if precision is not None:
        try:
            return str(round(float(value), precision))
        except (TypeError, ValueError):
            pass
    return str(value)


def extract_serial_number_from_channel_name(channel_name):
    """Return first hex-like serial substring embedded within channel name."""
    if channel_name is None:
        return None
    channel_str = channel_name if isinstance(channel_name, str) else str(channel_name)
    match = SERIAL_NUMBER_PATTERN.search(channel_str)
    if match:
        return match.group(0)
    return None


def extract_channel_components(channel_name):
    """Extract transceiver and transducer components from channel name.

    Expected formats:
        EK60: ``GPT  18 kHz 009072056b0e 2-1 ES18-11``
        EK80: ``WBT 978217-15 ES38-7_2``

    Args:
        channel_name: Channel identifier string.

    Returns:
        Dict with keys: transceiver_model, transceiver_number,
        transceiver_port, channel_instance_number, transducer_model.
    """
    if channel_name is None:
        return {}

    channel_str = channel_name if isinstance(channel_name, str) else str(channel_name)
    parts = channel_str.split()

    result = {
        "transceiver_model": None,
        "transceiver_number": None,
        "transceiver_port": None,
        "channel_instance_number": 1,
        "transducer_model": None
    }

    if len(parts) > 0:
        result["transceiver_model"] = parts[0]

    # Extract transceiver_number and transceiver_port from EK60 pattern (N-N)
    for part in parts:
        if '-' in part and part.replace('-', '').isdigit():
            nums = part.split('-')
            if len(nums) == 2:
                try:
                    result["transceiver_number"] = int(nums[0])
                    result["transceiver_port"] = int(nums[1])
                except ValueError:
                    pass
                break

    # Extract transducer_model (last part, before any underscore)
    if len(parts) > 0:
        last_part = parts[-1]
        if '_' in last_part:
            base, suffix = last_part.rsplit('_', 1)
            result["transducer_model"] = base
            try:
                result["channel_instance_number"] = int(suffix)
            except ValueError:
                result["channel_instance_number"] = 1
        else:
            result["transducer_model"] = last_part

    return result


def build_calibration_key(channel_data: dict, calibration_date: str = None) -> str:
    """Build a unique key for a channel configuration.

    This is the single source of truth for generating the key string used as
    the filename stem for single-channel calibration files, the key in
    ``calibration_dict``, the value in ``mapping_dict``, and the
    deduplication key for unique-channel extraction.

    Works with both raw channel dicts (which use ``channel_id``) and
    calibration channel dicts (which use ``channel``). Numeric fields are
    rounded to the precision specified in the JSON schema so that keys are
    consistent regardless of source.

    Format::

        <calibration_date>__<channel>__<transducer_serial_number>__<pulse_form>
        __<transmit_duration_nominal>__<transmit_power>__<frequency_start>
        __<frequency_end>

    Args:
        channel_data: Channel dictionary (raw or calibration format).
        calibration_date: Optional override for the calibration date. If
            None, the value is read from ``channel_data['calibration_date']``.

    Returns:
        Unique string key for the channel configuration.
    """
    if calibration_date is None:
        calibration_date = str(channel_data.get('calibration_date', ''))

    channel_name = channel_data.get('channel') or channel_data.get('channel_id', '')

    tsn = channel_data.get('transducer_serial_number')
    tsn_str = str(tsn) if tsn is not None else TRANSDUCER_SERIAL_UNKNOWN

    parts = [
        str(calibration_date),
        str(channel_name),
        tsn_str,
        str(channel_data.get('pulse_form', '')),
        _round_key_field('transmit_duration_nominal', channel_data),
        _round_key_field('transmit_power', channel_data),
        _round_key_field('frequency_start', channel_data),
        _round_key_field('frequency_end', channel_data),
    ]
    return '__'.join(parts)


def calibration_key_to_filename(cal_key: str) -> str:
    """Sanitize a calibration key for use as a filename stem.

    Replaces characters that are problematic in file paths (``/``, ``\\``,
    ``:``) with hyphens.

    Args:
        cal_key: The raw calibration key string.

    Returns:
        A filesystem-safe filename stem (without extension).
    """
    return cal_key.replace('/', '-').replace('\\', '-').replace(':', '-')


def _get_nominal_frequency_hz(channel_data: dict):
    """Extract the nominal transducer frequency in Hz as an integer.

    Looks at ``nominal_transducer_frequency`` first, then falls back to
    ``frequency_start``.

    Returns:
        Integer frequency in Hz, or None if unavailable.
    """
    freq = channel_data.get('nominal_transducer_frequency')
    if freq is None:
        freq = channel_data.get('frequency_start')
    if freq is None:
        return None
    try:
        return int(round(float(freq)))
    except (TypeError, ValueError):
        return None


def build_short_filename_map(
    cal_keys_to_channels: dict,
    calibration_date: str = None,
) -> dict:
    """Build a mapping from calibration keys to short filename stems.

    Groups channels by (calibration_date, nominal_transducer_frequency),
    then assigns a sequential configuration ID (config-1, config-2, ...)
    within each group.

    Short filename format::

        <calibration_date>__<frequency_hz>__config-<N>

    Args:
        cal_keys_to_channels: ``{cal_key: channel_data_dict, ...}``.
        calibration_date: Override calibration date for all entries. If
            None, each entry's ``calibration_date`` field is used.

    Returns:
        Dict mapping cal_key to short filename stem (without extension).
    """
    date_freq_groups: dict = {}
    for cal_key, channel_data in cal_keys_to_channels.items():
        freq = _get_nominal_frequency_hz(channel_data)
        date_str = calibration_date or str(channel_data.get('calibration_date', ''))
        date_freq_groups.setdefault((date_str, freq), []).append(cal_key)

    short_map: dict = {}
    for (date_str, freq), keys in date_freq_groups.items():
        for idx, cal_key in enumerate(keys, start=1):
            freq_str = str(freq) if freq is not None else 'unknown'
            short_map[cal_key] = f"{date_str}__{freq_str}__config-{idx}"

    return short_map


def remap_to_short_keys(
    mapping_dict: dict,
    calibration_dict: dict,
) -> tuple:
    """Remap long calibration keys to short identifiers in output dicts.

    The short identifier (e.g. ``2016-07-03__38000__config-1``) becomes the
    key used in the mapping and calibration configuration files, as well as
    the filename stem for individual ``.yaml`` files.

    Args:
        mapping_dict: ``{filename: {channel_id: long_cal_key, ...}, ...}``
        calibration_dict: ``{long_cal_key: cal_data_dict, ...}``

    Returns:
        Tuple of (remapped_mapping, remapped_calibration, short_map) where
        short_map is ``{long_key: short_key, ...}``.
    """
    base_short_map = build_short_filename_map(calibration_dict)

    short_map: dict = {}
    for cal_key, cal_data in calibration_dict.items():
        short_name = base_short_map[cal_key]
        base_filename = calibration_key_to_filename(build_calibration_key(cal_data))
        if cal_key != base_filename and cal_key.startswith(base_filename):
            short_name += cal_key[len(base_filename):]
        short_map[cal_key] = short_name

    new_mapping: dict = {}
    for filename, channels in mapping_dict.items():
        new_mapping[filename] = {
            ch_id: short_map.get(ck, ck) for ch_id, ck in channels.items()
        }

    new_calibration: dict = {
        short_map.get(ck, ck): cd for ck, cd in calibration_dict.items()
    }

    return new_mapping, new_calibration, short_map


def print_short_key_summary(short_map: dict, calibration_dict: dict):
    """Print a summary mapping short keys to calibration parameters.

    Groups output by nominal frequency.

    Args:
        short_map: ``{long_cal_key: short_key, ...}``
        calibration_dict: ``{long_cal_key: cal_data_dict, ...}``
    """
    freq_groups: dict = {}
    for long_key, short_key in short_map.items():
        freq = _get_nominal_frequency_hz(calibration_dict[long_key])
        freq_groups.setdefault(freq, []).append((short_key, long_key))

    print("\nShort key -> calibration parameters:")
    print("=" * 80)
    for freq in sorted(freq_groups.keys(), key=lambda f: f or 0):
        freq_label = f"{freq} Hz" if freq is not None else "Unknown frequency"
        print(f"\n  {freq_label}:")
        for short_key, long_key in freq_groups[freq]:
            cal_data = calibration_dict[long_key]
            model = cal_data.get('transducer_model', 'N/A')
            serial = cal_data.get('transducer_serial_number', 'N/A')
            pulse = cal_data.get('pulse_form', 'N/A')
            power = cal_data.get('transmit_power', 'N/A')
            duration = cal_data.get('transmit_duration_nominal', 'N/A')
            print(f"    {short_key}:")
            print(f"      Model: {model}, Serial: {serial}, Pulse form: {pulse}")
            print(f"      Power: {power} W, Duration: {duration} s")
