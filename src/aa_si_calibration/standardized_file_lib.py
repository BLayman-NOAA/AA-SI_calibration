"""Standardized calibration file I/O, schema validation, and key generation.

This module is the backbone for reading, writing, and validating the
standardized single-channel YAML calibration file format used throughout
the calibration pipeline.  It also provides the canonical
``build_calibration_key`` function that generates the unique identifiers
for channel configurations.
"""

from pathlib import Path
import numpy as np
import json
import datetime
import yaml
import jsonschema
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import re

from .constants import (
    SCHEMA_PATH,
    SERIAL_NUMBER_PATTERN,
    NOMINAL_FREQ_PATTERN,
    STRING_IDENTIFIER_FIELDS,
)
from .utils import extract_nominal_frequency_from_transducer_model


# Custom YAML dumper for standardized file output
class _StandardizedFileDumper(yaml.SafeDumper):
    """Custom YAML dumper that double-quotes strings and uses flow-style lists."""
    pass

def _str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')

def _list_representer(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

_StandardizedFileDumper.add_representer(str, _str_representer)
_StandardizedFileDumper.add_representer(list, _list_representer)


def ensure_string_identifiers(data):
    """Ensure specified identifier fields are stored as strings.
    
    Recursively processes dictionaries and lists to convert identifier
    fields to strings for consistent YAML output and matching.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in STRING_IDENTIFIER_FIELDS and value is not None:
                result[key] = str(value)
            else:
                result[key] = ensure_string_identifiers(value)
        return result
    elif isinstance(data, list):
        return [ensure_string_identifiers(item) for item in data]
    else:
        return data


def extract_degree_constraints(schema):
    """Extract min/max constraints for degree-based parameters from the schema.
    
    Returns a dict mapping field names to their (minimum, maximum) constraints
    for fields that have x-units: "arc_degree".
    """
    channel_props = schema.get("properties", {})
    degree_constraints = {}
    
    for field_name, metadata in channel_props.items():
        # Check if this is a degree-based field
        if metadata.get("x-units") != "arc_degree":
            continue
        
        # Get constraints from items (for array fields) or directly
        items = metadata.get("items", {})
        minimum = items.get("minimum", metadata.get("minimum"))
        maximum = items.get("maximum", metadata.get("maximum"))
        
        if minimum is not None or maximum is not None:
            degree_constraints[field_name] = (minimum, maximum)
    
    return degree_constraints


def sanitize_degree_values(channel_dict, schema):
    """Replace out-of-range degree values with null and notify user.
    
    For any parameter that should be in degrees (according to the schema),
    values outside the valid range are replaced with null due to instrument error.
    
    Args:
        channel_dict: A single channel dictionary to sanitize (modified in place)
        schema: The JSON schema for validation
        
    Returns:
        List of warning messages for values that were replaced
    """
    degree_constraints = extract_degree_constraints(schema)
    warnings = []
    
    channel_id = channel_dict.get("channel", "Unknown channel")
    
    for field_name, (minimum, maximum) in degree_constraints.items():
        value = channel_dict.get(field_name)
        
        if value is None:
            continue
        
        # Handle array fields
        if isinstance(value, (list, tuple)):
            sanitized_array = []
            for i, v in enumerate(value):
                if v is None:
                    sanitized_array.append(None)
                elif not isinstance(v, (int, float)):
                    sanitized_array.append(v)
                elif (minimum is not None and v < minimum) or (maximum is not None and v > maximum):
                    warnings.append(
                        f" {field_name}[{i}] = {v} is out of range [{minimum}, {maximum}] "
                        f"for channel '{channel_id}'. Replaced with null due to instrument error."
                    )
                    sanitized_array.append(None)
                else:
                    sanitized_array.append(v)
            channel_dict[field_name] = sanitized_array
        
        # Handle scalar fields
        elif isinstance(value, (int, float)):
            if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                warnings.append(
                    f" {field_name} = {value} is out of range [{minimum}, {maximum}] "
                    f"for channel '{channel_id}'. Replaced with null due to instrument error."
                )
                channel_dict[field_name] = None
    
    return warnings


def load_standardized_calibration_schema(schema_path=None):
    """Load and return the JSON schema for standardized calibration files."""
    schema_file = Path(schema_path) if schema_path else SCHEMA_PATH
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")
    with open(schema_file, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_channel_precision_map(schema):
    """Return a mapping of field name to x-precision from the schema."""
    channel_props = schema.get("properties", {})
    precision_map = {}
    for field_name, metadata in channel_props.items():
        precision = metadata.get("x-precision")
        if isinstance(precision, int):
            precision_map[field_name] = precision
    return precision_map


def is_numeric_value(value):
    """Return True if *value* is a numeric type (excluding bool)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float, np.integer, np.floating, Decimal))


def _quantize_decimal(value, precision):
    if value is None or not is_numeric_value(value):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if decimal_value.is_nan():
        return None
    quantizer = Decimal("1") if precision <= 0 else Decimal(f"1e-{precision}")
    try:
        return decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def round_numeric_value(value, precision):
    """Round a numeric value to the given decimal precision."""
    quantized = _quantize_decimal(value, precision)
    if quantized is None:
        return value
    return float(quantized)


def apply_precision_to_channel(channel_entry, precision_map):
    """Round all fields in *channel_entry* according to *precision_map*."""
    for field_name, precision in precision_map.items():
        if field_name in channel_entry:
            channel_entry[field_name] = round_numeric_value(channel_entry[field_name], precision)
    return channel_entry


def _value_exceeds_precision(value, precision):
    quantized = _quantize_decimal(value, precision)
    if quantized is None:
        return False
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if decimal_value.is_nan():
        return False
    return decimal_value != quantized


def enforce_precision_limits(channel_dict, precision_map):
    """Raise ValueError if any field exceeds the allowed precision."""
    for field_name, precision in precision_map.items():
        value = channel_dict.get(field_name)
        if _value_exceeds_precision(value, precision):
            channel_id = channel_dict.get("channel", "Unknown")
            raise ValueError(
                f"Channel '{channel_id}' field '{field_name}' exceeds allowed precision of {precision} decimal places"
            )


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
    - EK60: 'GPT  18 kHz 009072056b0e 2-1 ES18-11'
    - EK80: 'WBT 978217-15 ES38-7_2'
    
    Returns dict with: transceiver_model, transceiver_number, transceiver_port, 
                       channel_instance_number, transducer_model
    """
    if channel_name is None:
        return {}
    
    channel_str = channel_name if isinstance(channel_name, str) else str(channel_name)
    parts = channel_str.split()
    
    result = {
        "transceiver_model": None,
        "transceiver_number": None,
        "transceiver_port": None,
        "channel_instance_number": 1,  # Default to 1
        "transducer_model": None
    }
    
    # Extract transceiver_model (first word)
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
    # Also extract channel_instance_number from suffix (e.g., "_2")
    if len(parts) > 0:
        last_part = parts[-1]
        # Check for EK80-style instance suffix (e.g., "ES38-7_2")
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


def convert_params_to_standardized_names(channels, cal_params, env_params, other_params):
    """Convert parsed calibration parameters into the standardized naming convention.

    Takes the raw parameter dictionaries produced by the manufacturer file parsers
    (or manually assembled) and maps each source key to the corresponding
    standardized field name.  Scalar parameters are broadcast to every channel;
    per-channel parameters are indexed.  Values that the schema marks as
    requiring an array wrapper are wrapped in a single-element list.

    Additional derived fields (transceiver_id, transceiver_model, transducer_model,
    channel components, source file metadata, etc.) are populated by inspecting
    the channel name and *other_params* entries.

    Args:
        channels: List of channel name strings (one per channel).
        cal_params: Dict of calibration parameters (gain, sa correction, beam
            angles, etc.). Values are per-channel lists.
        env_params: Dict of environmental parameters (sound speed, absorption,
            temperature, salinity, etc.). May be scalar or per-channel.
        other_params: Dict of additional parameters (frequency, pulse form,
            serial numbers, source file info, etc.).

    Returns:
        List of dicts, one per channel, with keys using the standardized names
        defined by the calibration file schema.
    """
    # Mapping: (source_dict_name, source_key, is_scalar, requires_array) -> standardized_key
    # If is_scalar=True, don't index; otherwise index by channel
    # If requires_array=True, wrap scalar values in single-element array
    param_mapping = [
        # cal_params - all indexed by channel, some now require arrays
        ("cal_params", "equivalent_beam_angle", False, False, "equivalent_beam_angle"),
        ("cal_params", "gain_correction", False, True, "gain_correction"),
        ("cal_params", "sa_correction", False, True, "sa_correction"),
        ("cal_params", "beamwidth_athwartship", False, True, "beamwidth_transmit_major"),
        ("cal_params", "beamwidth_athwartship", False, True, "beamwidth_receive_major"),
        ("cal_params", "beamwidth_alongship", False, True, "beamwidth_transmit_minor"),
        ("cal_params", "beamwidth_alongship", False, True, "beamwidth_receive_minor"),
        ("cal_params", "angle_offset_athwartship", False, True, "echoangle_major"),
        ("cal_params", "angle_offset_alongship", False, True, "echoangle_minor"),
        ("cal_params", "angle_sensitivity_athwartship", False, True, "echoangle_major_sensitivity"),
        ("cal_params", "angle_sensitivity_alongship", False, True, "echoangle_minor_sensitivity"),
        
        # env_params - sound_speed is scalar, absorption is indexed
        ("env_params", "sound_speed", True, False, "sound_speed_indicative"),
        ("env_params", "sound_absorption", False, False, "absorption_indicative"),
        # EK80-specific environmental params (scalar - same value for all channels)
        ("env_params", "temperature", True, False, "temperature"),
        ("env_params", "salinity", True, False, "salinity"),
        ("env_params", "pH", True, False, "acidity"),
        ("env_params", "pressure", True, False, "pressure"),
        
        # other_params - mix of scalar and indexed, frequency now requires array
        ("other_params", "frequency_nominal", False, True, "frequency"),
        ("other_params", "sonar_software_version", True, False, "sonar_software_version"),
        ("other_params", "sonar_software_name", True, False, "sonar_software_name"),
        ("other_params", "transmit_power", False, False, "transmit_power"),
        ("other_params", "transmit_duration_nominal", False, False, "transmit_duration_nominal"),
        ("other_params", "transmit_bandwidth", False, False, "transmit_bandwidth"),
        ("other_params", "sample_interval", False, False, "sample_interval"),
        ("other_params", "date", False, False, "calibration_date"),
        ("other_params", "comments", False, False, "calibration_comments"),
        # EK80-specific parameters (indexed by channel)
        ("other_params", "frequency_start", False, False, "frequency_start"),
        ("other_params", "frequency_end", False, False, "frequency_end"),
        ("other_params", "pulse_form", False, False, "pulse_form"),
        ("other_params", "beam_type", False, False, "beam_type"),
        ("other_params", "sphere_diameter", False, False, "sphere_diameter"),
        ("other_params", "sphere_material", False, False, "sphere_material"),
        ("other_params", "transducer_serial", False, False, "transducer_serial_number"),
        ("other_params", "transceiver_serial", False, False, "transceiver_serial_number"),
        ("other_params", "nominal_transducer_frequency", False, False, "nominal_transducer_frequency"),
    ]
    
    param_sources = {
        "cal_params": cal_params,
        "env_params": env_params,
        "other_params": other_params
    }
    
    converted_params = []
    source_filenames_by_channel = other_params.get("source_filenames_by_channel")
    source_filenames_across_channels = other_params.get("source_filenames_across_channels")
    source_file_type_data = other_params.get("source_file_type")
    source_file_location_data = other_params.get("source_file_location")
    source_file_paths_data = other_params.get("source_file_paths")

    def normalize_date_to_iso8601(date_value):
        """Convert date strings like MM/DD/YYYY to ISO 8601 format (YYYY-MM-DD).
        
        Handles common formats: MM/DD/YYYY, M/D/YYYY, MM-DD-YYYY, M-D-YYYY.
        Returns original value if already in ISO format or cannot be parsed.
        """
        if date_value is None:
            return None
        if not isinstance(date_value, str):
            return date_value
        
        date_str = date_value.strip()
        
        # Already in ISO format (YYYY-MM-DD)?
        if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
            return date_str
        
        # Try common US formats: MM/DD/YYYY or M/D/YYYY
        for sep in ['/', '-']:
            if sep in date_str:
                parts = date_str.split(sep)
                if len(parts) == 3:
                    try:
                        month = int(parts[0])
                        day = int(parts[1])
                        year = int(parts[2])
                        # Validate ranges
                        if 1 <= month <= 12 and 1 <= day <= 31 and year >= 1900:
                            return f"{year:04d}-{month:02d}-{day:02d}"
                    except ValueError:
                        pass
        
        # Could not parse, return original
        return date_value

    def normalize_source_list(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple, np.ndarray)):
            normalized = [str(item) for item in raw_value if item is not None]
            return normalized or None
        return [str(raw_value)]

    def normalize_source_location(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple, np.ndarray)):
            normalized = [str(item) for item in raw_value if item is not None]
            return ", ".join(normalized) if normalized else None
        return str(raw_value)

    def normalize_path_list(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple, np.ndarray)):
            normalized = [str(item) for item in raw_value if item is not None]
            return normalized or None
        return [str(raw_value)]

    def resolve_source_file_type(raw_value, index):
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple, np.ndarray)):
            try:
                candidate = raw_value[index]
            except (IndexError, TypeError):
                candidate = None
            return str(candidate) if candidate is not None else None
        return str(raw_value)

    normalized_location = normalize_source_location(source_file_location_data)
    normalized_paths = normalize_path_list(source_file_paths_data)
    
    for idx, channel in enumerate(channels):
        channel_payload = {"channel": channel}
        
        # Process all parameters
        for source_name, source_key, is_scalar, requires_array, std_key in param_mapping:
            data = param_sources[source_name].get(source_key)
            
            if data is None:
                value = None
            elif is_scalar:
                # Scalar field: if someone passed a list, index into it and warn
                if isinstance(data, (list, tuple, np.ndarray)):
                    print(f"  WARNING: '{source_key}' is declared scalar but received "
                          f"a list (length {len(data)}). Using element [{idx}].")
                    try:
                        value = data[idx]
                    except (IndexError, TypeError):
                        print(f"  WARNING: Could not index '{source_key}' at [{idx}], "
                              f"setting '{std_key}' to None.")
                        value = None
                else:
                    value = data
            else:
                # Indexed field: if someone passed a scalar, broadcast it and warn
                if not isinstance(data, (list, tuple, np.ndarray)):
                    print(f"  WARNING: '{source_key}' is declared per-channel but received "
                          f"a scalar ({data}). Broadcasting to all channels.")
                    value = data
                else:
                    try:
                        value = data[idx]
                    except (IndexError, TypeError):
                        print(f"  WARNING: Could not index '{source_key}' at [{idx}] "
                              f"(length {len(data) if hasattr(data, '__len__') else '?'}), "
                              f"setting '{std_key}' to None.")
                        value = None
            
            # Wrap in array if required and value is not None and not already an array
            if requires_array and value is not None:
                if not isinstance(value, (list, tuple, np.ndarray)):
                    value = [value]
            
            channel_payload[std_key] = value

        channel_sources = None
        if source_filenames_by_channel is not None:
            try:
                channel_sources = source_filenames_by_channel[idx]
            except (IndexError, TypeError):
                channel_sources = None
        elif source_filenames_across_channels is not None:
            channel_sources = source_filenames_across_channels

        # Extract transceiver_id and transceiver_ethernet_address
        # Priority: 1) transceiver_serial_number from params (EK80), 2) extracted from channel name (EK60)
        extracted_serial = extract_serial_number_from_channel_name(channel)
        transceiver_serial_from_params = channel_payload.get("transceiver_serial_number")
        
        # Use transceiver_serial_number if available, otherwise fall back to extracted serial
        if transceiver_serial_from_params is not None:
            channel_payload["transceiver_id"] = transceiver_serial_from_params
            channel_payload["transceiver_ethernet_address"] = transceiver_serial_from_params
        else:
            channel_payload["transceiver_id"] = extracted_serial
            channel_payload["transceiver_ethernet_address"] = extracted_serial
        
        # Extract additional channel components
        channel_components = extract_channel_components(channel)
        channel_payload["transceiver_model"] = channel_components.get("transceiver_model")
        channel_payload["transceiver_number"] = channel_components.get("transceiver_number")
        channel_payload["transceiver_port"] = channel_components.get("transceiver_port")
        channel_payload["channel_instance_number"] = channel_components.get("channel_instance_number")
        channel_payload["transducer_model"] = channel_components.get("transducer_model")
        
        # Override transceiver_model and transducer_model with explicit values from
        # other_params when available (EK80 XML provides these as distinct fields
        # rather than embedded in the channel name)
        transceiver_type_list = other_params.get("transceiver_type")
        if transceiver_type_list is not None:
            if isinstance(transceiver_type_list, (list, tuple, np.ndarray)):
                if idx < len(transceiver_type_list) and transceiver_type_list[idx] is not None:
                    channel_payload["transceiver_model"] = transceiver_type_list[idx]
            else:
                channel_payload["transceiver_model"] = transceiver_type_list
        
        transducer_list = other_params.get("transducer")
        if transducer_list is not None:
            if isinstance(transducer_list, (list, tuple, np.ndarray)):
                if idx < len(transducer_list) and transducer_list[idx] is not None:
                    channel_payload["transducer_model"] = transducer_list[idx]
            else:
                channel_payload["transducer_model"] = transducer_list
        
        # multiplexing_found is not determinable from channel name alone for EK60
        # It would need to be passed in or determined by analyzing all channels
        channel_payload["multiplexing_found"] = None
        
        # Set frequency_start and frequency_end (use param_mapping values if available,
        # otherwise derive from frequency array for EK60 CW mode)
        if channel_payload.get("frequency_start") is None and channel_payload.get("frequency") is not None:
            freq_array = channel_payload["frequency"]
            if isinstance(freq_array, (list, tuple, np.ndarray)) and len(freq_array) > 0:
                # For EK60 (single frequency), both start and end are the same
                channel_payload["frequency_start"] = freq_array[0]
                channel_payload["frequency_end"] = freq_array[-1]
        
        # Set pulse_form only if not already set from params (default "0" for EK60 CW)
        if channel_payload.get("pulse_form") is None:
            channel_payload["pulse_form"] = "0"
        elif channel_payload.get("pulse_form") is not None:
            # Ensure pulse_form is a string
            channel_payload["pulse_form"] = str(channel_payload["pulse_form"])

        # Convert calibration_date to ISO 8601 format if needed
        if channel_payload.get("calibration_date") is not None:
            channel_payload["calibration_date"] = normalize_date_to_iso8601(channel_payload["calibration_date"])

        channel_payload["source_filenames"] = normalize_source_list(channel_sources)
        channel_payload["source_file_type"] = resolve_source_file_type(source_file_type_data, idx)
        channel_payload["source_file_location"] = normalized_location
        channel_payload["source_file_paths"] = list(normalized_paths) if normalized_paths is not None else None
        
        converted_params.append(channel_payload)

    return converted_params


def convert_numpy_scalars(obj):
    """Recursively convert numpy scalar types to native Python types."""
    if isinstance(obj, dict):
        # Convert ALL keys to str, including numpy.str_
        return {str(k): convert_numpy_scalars(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_scalars(v) for v in obj]
    elif isinstance(obj, np.generic):
        return obj.item()
    else:
        return obj
        


def validate_standardized_calibration_dict(calibration_dict, schema_path):
    """Validate a single-channel calibration dictionary against the JSON Schema file."""
    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")
    schema = load_standardized_calibration_schema(schema_file)
    jsonschema.validate(instance=calibration_dict, schema=schema)
    precision_map = extract_channel_precision_map(schema)
    enforce_precision_limits(calibration_dict, precision_map)
    print("data validated by json schema")
    return True


def assign_parameters_to_standardized_dictionary(
    channel_params,
    global_params
    ):
    """Assemble validated standardized calibration channel dicts from channel and global params.
    
    Returns a list of channel dictionaries, sorted by frequency.
    """
    # Generate a shared timestamp for all channels in this batch
    record_created_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    schema = load_standardized_calibration_schema()
    precision_map = extract_channel_precision_map(schema)

    def _sort_key(params):
        freq = params.get("nominal_transducer_frequency")
        if freq is None:
            freq = params.get("frequency")
        if freq is None:
            return float("inf")
        if isinstance(freq, (list, tuple)):
            return freq[0] if freq else float("inf")
        return freq

    sorted_channels = sorted(channel_params, key=_sort_key)

    channel_dicts = []
    for channel_param in sorted_channels:
        channel_entry = get_empty_channel_params()
        for param_name, value in channel_param.items():
            if param_name in channel_entry:
                channel_entry[param_name] = value
        # Always set record_created timestamp when creating channel records
        channel_entry["record_created"] = record_created_timestamp
        # Set record_author from global_params if not already set on the channel
        if channel_entry.get("record_author") is None and global_params.get("record_author") is not None:
            channel_entry["record_author"] = global_params["record_author"]
        channel_entry = apply_precision_to_channel(channel_entry, precision_map)
        channel_entry = convert_numpy_scalars(channel_entry)

        # Sanitize out-of-range degree values before validation
        degree_warnings = sanitize_degree_values(channel_entry, schema)
        if degree_warnings:
            print("\n" + "=" * 80)
            print("DEGREE VALUE SANITIZATION WARNINGS")
            print("=" * 80)
            for warning in degree_warnings:
                print(warning)
            print("=" * 80 + "\n")

        channel_dicts.append(channel_entry)

    return channel_dicts


def get_empty_top_level_params():
    """Return a skeleton top-level standardized calibration dictionary."""
    empty_channel_data = {
        "cruise_id": None,
        "calibration_report_title": None,
        "calibration_report_DOI": None,
        "calibration_report": None,
        "channels": []
    }
    return empty_channel_data  


def get_empty_channel_params():
    """Return a skeleton channel-level dictionary with all fields set to None."""
    empty_channel_data = {
        # Source file provenance (first for quick identification)
        "source_filenames": None,
        # Record metadata
        "record_created": None,
        "record_author": None,
        # Channel identification
        "channel": None,
        "transceiver_id": None,
        "transceiver_model": None,
        "transceiver_ethernet_address": None,
        "transceiver_serial_number": None,
        "transceiver_number": None,
        "transceiver_port": None,
        "channel_instance_number": None,
        "transducer_model": None,
        "transducer_serial_number": None,
        "pulse_form": None,
        "frequency_start": None,
        "frequency_end": None,
        "nominal_transducer_frequency": None,
        "transmit_power": None,
        "transmit_duration_nominal": None,
        "multiplexing_found": None,
        # Calibration metadata
        "calibration_date": None,
        "calibration_comments": None,
        "calibration_version": None,
        # Environmental parameters
        "absorption_indicative": None,
        "sound_speed_indicative": None,
        # Physical environment
        "temperature": None,
        "salinity": None,
        "acidity": None,
        "pressure": None,
        # Optional scalar parameters
        "sample_interval": None,
        "transmit_bandwidth": None,
        "beam_type": None,
        "calibration_acquisition_method": None,
        "sphere_diameter": None,
        "sphere_material": None,
        # Source file info (scalars)
        "source_file_type": None,
        "source_file_location": None,
        "sonar_software_version": None,
        "sonar_software_name": None,
        # Equivalent beam angle (just above arrays)
        "equivalent_beam_angle": None,
        # Array parameters
        "gain_correction": None,
        "sa_correction": None,
        "frequency": None,
        "beamwidth_transmit_major": None,
        "beamwidth_receive_major": None,
        "beamwidth_transmit_minor": None,
        "beamwidth_receive_minor": None,
        "echoangle_major": None,
        "echoangle_minor": None,
        "echoangle_major_sensitivity": None,
        "echoangle_minor_sensitivity": None,
        "source_file_paths": None,
    }
    return empty_channel_data  


def get_calibration_file_names_from_folder(source_cal_folder):
    """Return a list of .raw and .cal file names found in *source_cal_folder*."""
    file_names = []

    if source_cal_folder is not None:

        for f in source_cal_folder.iterdir():
            if f.is_file():
                if f.suffix == ".raw" or f.suffix == ".cal":
                    file_names.append(f.name)
                else:
                    print("File ignored because of extension: " + f.name + "" + f.suffix)
    return file_names


# combined method for saving standardized file
def save_cal_params_to_standardized_file(
    cal_params,
    env_params,
    other_params,
    other_global_params=None,
    standardized_cal_file_path=None
):
    """Save calibration parameters to a single multi-channel standardized YAML file.

    .. deprecated::
        This function saves all channels into one multi-channel file.  The
        preferred approach is :func:`save_single_channel_files_from_params`,
        which writes each channel as an individual file, the canonical
        intermediate format used by both the full pipeline and the
        user-provided calibration pipeline.  This function is retained for
        backward compatibility but is no longer actively developed.
    """
    import warnings
    warnings.warn(
        "save_cal_params_to_standardized_file is deprecated. "
        "Use save_single_channel_files_from_params instead, which saves each "
        "channel as an individual file (the canonical intermediate format).",
        DeprecationWarning,
        stacklevel=2,
    )

    if other_global_params is None:
        other_global_params = {}
    if standardized_cal_file_path is None:
        raise ValueError("Must provide standardized_cal_file_path parameters")

    converted_channel_params = convert_params_to_standardized_names(other_params["channel"], cal_params, env_params, other_params)

    channel_dicts = assign_parameters_to_standardized_dictionary(converted_channel_params, other_global_params)
    channel_dicts = [ensure_string_identifiers(ch) for ch in channel_dicts]

    schema_path = SCHEMA_PATH
    
    # Validate each channel individually against the single-channel schema
    for channel_dict in channel_dicts:
        validate_standardized_calibration_dict(channel_dict, schema_path)

    # Build legacy multi-channel structure for file output
    standardized_dictionary = get_empty_top_level_params()
    for global_param, value in other_global_params.items():
        if global_param in standardized_dictionary and global_param != "channels":
            standardized_dictionary[global_param] = value
    standardized_dictionary["channels"] = channel_dicts

    try:
        with open(standardized_cal_file_path, 'w') as file:
            # file is the open file stream object
            yaml.dump(standardized_dictionary, file, Dumper=_StandardizedFileDumper, sort_keys=False)
        
        print(f"Data successfully saved to {standardized_cal_file_path}")

    except Exception as e:
        print(f"An error occurred while writing the file: {e}")


# Schema-derived precisions for the numeric fields used in the calibration key.
# Loaded once; kept at module level for efficiency.
_KEY_FIELD_PRECISIONS = {
    'transmit_duration_nominal': 6,   # x-precision in schema
    'transmit_power': 10,             # x-precision in schema
    'frequency_start': 10,            # x-precision in schema
    'frequency_end': 10,              # x-precision in schema
}


def build_calibration_key(channel_data: dict, calibration_date: str = None) -> str:
    """
    Build a unique key for a channel configuration.

    This is the **single source of truth** for generating the key string used
    as:

    * The filename stem for single-channel calibration files.
    * The key in ``calibration_dict``.
    * The value in ``mapping_dict``.
    * The deduplication key for unique-channel extraction.

    Works with both *raw* channel dicts (which use ``channel_id``) and
    *calibration* channel dicts (which use ``channel``).  Numeric fields are
    rounded to the precision specified in the JSON schema so that keys are
    consistent regardless of source.

    Format::

        <calibration_date>__<channel>__<transducer_serial_number>__<pulse_form>
        __<transmit_duration_nominal>__<transmit_power>__<frequency_start>
        __<frequency_end>

    Args:
        channel_data: Channel dictionary (raw or calibration format).
        calibration_date: Optional override for the calibration date.  If
            *None*, the value is read from ``channel_data['calibration_date']``.

    Returns:
        Unique string key for the channel configuration.
    """
    # Resolve calibration_date
    if calibration_date is None:
        calibration_date = str(channel_data.get('calibration_date', ''))

    # Resolve channel name: prefer 'channel', fall back to 'channel_id'
    channel_name = channel_data.get('channel') or channel_data.get('channel_id', '')

    # Handle missing transducer_serial_number (always None for EK60)
    tsn = channel_data.get('transducer_serial_number')
    tsn_str = str(tsn) if tsn is not None else 'NoSN'

    def _round_field(field_name):
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

    parts = [
        str(calibration_date),
        str(channel_name),
        tsn_str,
        str(channel_data.get('pulse_form', '')),
        _round_field('transmit_duration_nominal'),
        _round_field('transmit_power'),
        _round_field('frequency_start'),
        _round_field('frequency_end'),
    ]
    return '__'.join(parts)


def calibration_key_to_filename(cal_key: str) -> str:
    """
    Sanitize a calibration key for use as a filename stem.

    Replaces characters that are problematic in file paths (``/``, ``\\``,
    ``:``) with hyphens.

    Args:
        cal_key: The raw calibration key string (from :func:`build_calibration_key`).

    Returns:
        A filesystem-safe filename stem (without extension).
    """
    return cal_key.replace('/', '-').replace('\\', '-').replace(':', '-')


def _strip_internal_keys(data: dict) -> dict:
    """Return a copy of *data* with internal tracking keys removed.

    Internal keys start with ``_`` (e.g. ``_calibration_file_key``).
    """
    return {k: v for k, v in data.items() if not k.startswith('_')}


def _get_nominal_frequency_hz(channel_data: dict):
    """Extract the nominal transducer frequency in Hz as an integer.

    Looks at ``nominal_transducer_frequency`` first, then falls back to
    ``frequency_start``.

    Returns:
        Integer frequency in Hz, or *None* if unavailable.
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

    Groups channels by ``(calibration_date, nominal_transducer_frequency)``,
    then assigns a sequential configuration ID (``config-1``, ``config-2``,
    …) within each group.

    Short filename format::

        <calibration_date>__<frequency_hz>__config-<N>

    Args:
        cal_keys_to_channels: ``{cal_key: channel_data_dict, …}``.  The
            channel data must contain ``nominal_transducer_frequency`` (or
            ``frequency_start`` as fallback) and optionally
            ``calibration_date``.
        calibration_date: Override calibration date for all entries.  If
            *None*, each entry's ``calibration_date`` field is used.

    Returns:
        Dict mapping ``cal_key`` → short filename stem (without extension).
    """
    # Group cal_keys by (calibration_date, nominal_frequency) so that the
    # config-N counter resets for each unique date + frequency combination.
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
        mapping_dict: ``{filename: {channel_id: long_cal_key, …}, …}``
        calibration_dict: ``{long_cal_key: cal_data_dict, …}``

    Returns:
        ``(remapped_mapping, remapped_calibration, short_map)`` where
        *short_map* is ``{long_key: short_key, …}``.
    """
    # Build short names from the full calibration dict.  After duplicate-
    # checking, each configuration is unique, so build_short_filename_map
    # assigns a distinct config-N per entry.
    base_short_map = build_short_filename_map(calibration_dict)

    # Carry over any disambiguation suffix (e.g. "__1") that was appended
    # at save time.  The suffix is the portion of the dict key beyond the
    # base filename derived from the channel data.
    short_map: dict = {}
    for cal_key, cal_data in calibration_dict.items():
        short_name = base_short_map[cal_key]
        base_filename = calibration_key_to_filename(build_calibration_key(cal_data))
        if cal_key != base_filename and cal_key.startswith(base_filename):
            short_name += cal_key[len(base_filename):]  # e.g. "__1"
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
    """Print an informational summary mapping short keys to calibration parameters.

    Groups output by nominal frequency so users can see which ``config-N``
    corresponds to which physical configuration.

    Args:
        short_map: ``{long_cal_key: short_key, …}`` as returned by
            :func:`build_short_filename_map` or :func:`remap_to_short_keys`.
        calibration_dict: ``{long_cal_key: cal_data_dict, …}``
    """
    # Group by frequency for organized display
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


def get_calibration_from_file(
    filename: str,
    channel_id: str,
    mapping_dict: dict,
    cal_files_dir,
):
    """
    Retrieve calibration data for a specific raw file and channel by reading
    from individual single-channel calibration YAML files.

    Works with both long keys (e.g.
    ``2016-07-03_ES38B_123456_CW_38000_38000_2000.0_0.001024``) and short
    keys (e.g. ``2016-07-03__38000__config-1``).  The key stored in
    *mapping_dict* is sanitised via :func:`calibration_key_to_filename` and
    used directly as the filename stem.

    Args:
        filename: Raw file name (e.g. ``'D20160725-T205832.raw'``).
        channel_id: Channel ID (e.g. ``'GPT  38 kHz 009072… ES38B'``).
        mapping_dict: The mapping dictionary (``filename -> channel_id -> cal_key``).
        cal_files_dir: Path to the directory containing individual
            single-channel ``.yaml`` calibration files.

    Returns:
        Calibration data dictionary, or *None* if not found.
    """
    if filename not in mapping_dict:
        return None

    if channel_id not in mapping_dict[filename]:
        return None

    cal_key = mapping_dict[filename][channel_id]
    cal_files_dir = Path(cal_files_dir)
    cal_file_path = cal_files_dir / f"{calibration_key_to_filename(cal_key)}.yaml"
    if not cal_file_path.exists():
        cal_file_path = cal_files_dir / f"{calibration_key_to_filename(cal_key)}.yml"
    if not cal_file_path.exists():
        return None

    with open(cal_file_path, 'r') as f:
        return yaml.safe_load(f)


def save_single_channel_files(
    channel_dicts,
    output_dir,
    key_func=None,
    short_filenames=False,
):
    """
    Save each channel from a list of channel dictionaries as an
    individual single-channel YAML file.

    Each channel is saved as a flat YAML dictionary.  The filename is derived
    from :func:`build_calibration_key` (or a custom *key_func*) and then
    either sanitized directly (long filenames) or mapped to a compact name
    via :func:`build_short_filename_map` (short filenames).

    Args:
        channel_dicts: List of channel dictionaries to save.
        output_dir: Directory to save individual channel files.
        key_func: Optional ``callable(channel_dict) -> str`` that returns the
            calibration key.  If *None*, uses :func:`build_calibration_key`.
        short_filenames: If ``True``, use the compact
            ``<date>__<freq>__config-<N>`` naming scheme instead of the full
            calibration key.

    Returns:
        Tuple of ``(saved_count, output_dir_path)``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if key_func is None:
        key_func = build_calibration_key

    channels = channel_dicts if isinstance(channel_dicts, list) else []

    # Group channels by their base calibration key to detect duplicates
    base_key_groups: dict = {}  # base_key -> [channel_data, ...]
    for channel_data in channels:
        base_key = key_func(channel_data)
        base_key_groups.setdefault(base_key, []).append(channel_data)

    # Build the full key -> channel_data mapping.
    # When duplicates exist, append __1, __2, etc. to distinguish them.
    keyed_channels: dict = {}
    for base_key, group in base_key_groups.items():
        if len(group) == 1:
            keyed_channels[base_key] = group[0]
        else:
            for idx, ch_data in enumerate(group, start=1):
                keyed_channels[f"{base_key}__{idx}"] = ch_data

    # Warn about duplicates
    dup_bases = [k for k, v in base_key_groups.items() if len(v) > 1]
    if dup_bases:
        print(f"\n⚠️  WARNING: {len(dup_bases)} calibration key(s) appeared "
              f"more than once (same configuration from multiple source files).")
        print("   Disambiguation suffixes (__1, __2, …) have been appended.")
        for base_key in dup_bases:
            print(f"\n   Key: {base_key}")
            for idx, ch_data in enumerate(base_key_groups[base_key], start=1):
                src = ch_data.get('source_filenames', ['unknown'])
                print(f"      __{idx}: {src}")

    # Build filename mapping
    if short_filenames:
        # Short names must group by base config so duplicates share config-N.
        base_representatives = {k: v[0] for k, v in base_key_groups.items()}
        base_short_map = build_short_filename_map(base_representatives)
        filename_map = {}
        for full_key, ch_data in keyed_channels.items():
            base_key = key_func(ch_data)
            base_short = base_short_map[base_key]
            suffix = full_key[len(base_key):] if full_key != base_key else ''
            filename_map[full_key] = f"{base_short}{suffix}"
    else:
        # Long names: sanitize the full key directly (includes any __N suffix)
        filename_map = {k: calibration_key_to_filename(k) for k in keyed_channels}

    # Save files
    saved_count = 0
    for full_key, channel_data in keyed_channels.items():
        file_stem = filename_map[full_key]
        file_path = output_dir / f"{file_stem}.yaml"

        channel_data_cleaned = _strip_internal_keys(ensure_string_identifiers(channel_data))

        with open(file_path, 'w') as f:
            yaml.dump(channel_data_cleaned, f, Dumper=_StandardizedFileDumper, default_flow_style=False, sort_keys=False)

        saved_count += 1

    return saved_count, output_dir


def save_individual_calibration_files(
    calibration_dict_keyed,
    output_dir,
    short_filenames=False,
):
    """
    Save each calibration entry from a keyed dictionary as a separate YAML
    file.

    Unlike :func:`save_single_channel_files` (which takes a list of channels
    and builds keys), this function accepts a dictionary that is **already
    keyed** by calibration key, for example ``MappingResult.calibration_dict``.

    Args:
        calibration_dict_keyed: ``{cal_key: channel_data_dict, ...}``
        output_dir: Directory to save individual calibration files.
        short_filenames: If ``True``, use compact filenames.

    Returns:
        Number of files saved.
    """
    import datetime as _dt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

    # Ensure record_created is set
    for cal_data in calibration_dict_keyed.values():
        if cal_data.get('record_created') is None:
            cal_data['record_created'] = shared_timestamp

    # Build filename mapping
    if short_filenames:
        filename_map = build_short_filename_map(calibration_dict_keyed)
    else:
        filename_map = {
            k: calibration_key_to_filename(k) for k in calibration_dict_keyed
        }

    saved_count = 0
    for cal_key, cal_data in calibration_dict_keyed.items():
        cal_data_cleaned = _strip_internal_keys(ensure_string_identifiers(cal_data))

        file_stem = filename_map[cal_key]
        file_path = output_dir / f"{file_stem}.yaml"

        with open(file_path, 'w') as f:
            yaml.dump(cal_data_cleaned, f, Dumper=_StandardizedFileDumper, default_flow_style=False, sort_keys=False)
        saved_count += 1

    return saved_count


def save_single_channel_files_from_params(
    cal_params,
    env_params,
    other_params,
    other_global_params=None,
    output_dir=None,
    short_filenames=False,
):
    """
    Parse manufacturer calibration parameters, validate, and save as
    individual single-channel YAML files (one per channel).
    
    This is the single-channel equivalent of ``save_cal_params_to_standardized_file``.
    Instead of producing one multi-channel file, it produces N individual files.
    
    Args:
        cal_params: Calibration parameters dictionary (from manufacturer parser).
        env_params: Environmental parameters dictionary.
        other_params: Other parameters dictionary (must include 'channel' key).
        other_global_params: Optional global parameters (e.g. cruise_id).
        output_dir: Directory to save individual channel files.
        short_filenames: If ``True``, use compact
            ``<date>__<freq>__config-<N>`` naming scheme.
    
    Returns:
        Tuple of (saved_count, output_dir_path, standardized_dict)
        The standardized_dict is also returned for optional further use.
    """
    if other_global_params is None:
        other_global_params = {}
    if output_dir is None:
        raise ValueError("Must provide output_dir")
    
    # Reuse the same conversion and validation pipeline as the multi-channel path
    converted_channel_params = convert_params_to_standardized_names(
        other_params["channel"], cal_params, env_params, other_params
    )
    channel_dicts = assign_parameters_to_standardized_dictionary(
        converted_channel_params, other_global_params
    )
    channel_dicts = [ensure_string_identifiers(ch) for ch in channel_dicts]
    
    # Validate each channel against schema
    for channel_dict in channel_dicts:
        validate_standardized_calibration_dict(channel_dict, SCHEMA_PATH)
    
    # Save each channel as an individual file
    saved_count, output_dir = save_single_channel_files(
        channel_dicts, output_dir, short_filenames=short_filenames
    )
    
    return saved_count, output_dir, channel_dicts


def create_calibration_template(channel: dict, calibration_date: str) -> dict:
    """
    Create a calibration template from a raw file channel configuration.

    Pre-fills channel identification parameters and leaves calibration values
    as ``None`` for the user to fill in.

    Args:
        channel: Raw channel configuration dictionary (as returned by the
            raw reader extraction functions).
        calibration_date: Calibration date string (``YYYY-MM-DD``).

    Returns:
        Template dictionary ready for serialization. ``record_created`` is left
        as ``None``. The caller should set it at the batch level.
    """
    # Round transmit_duration to standard precision
    transmit_duration = round(channel.get('transmit_duration_nominal', 0), 6)

    template = {
        # Record metadata (auto-generated when saving)
        'record_created': None,
        'record_author': None,

        # Channel identification (from raw file - DO NOT MODIFY)
        'channel': channel.get('channel_id'),
        'transceiver_id': channel.get('transceiver_id'),
        'transceiver_model': channel.get('transceiver_model'),
        'transceiver_ethernet_address': channel.get('transceiver_ethernet_address'),
        'transceiver_serial_number': channel.get('transceiver_serial_number'),
        'transceiver_number': channel.get('transceiver_number'),
        'transceiver_port': channel.get('transceiver_port'),
        'channel_instance_number': channel.get('channel_instance_number'),
        'transducer_model': channel.get('transducer_model'),
        'transducer_serial_number': channel.get('transducer_serial_number'),
        'pulse_form': str(channel.get('pulse_form', '0')),
        'frequency_start': channel.get('frequency_start'),
        'frequency_end': channel.get('frequency_end'),
        'frequency': [channel.get('frequency')],
        'nominal_transducer_frequency': channel.get('nominal_transducer_frequency'),
        'transmit_power': channel.get('transmit_power'),
        'transmit_duration_nominal': transmit_duration,
        'multiplexing_found': channel.get('multiplexing_found', False),

        # Calibration metadata (USER FILLS IN)
        'calibration_date': calibration_date,
        'calibration_comments': None,
        'calibration_version': None,

        # Core calibration values (USER FILLS IN - REQUIRED)
        'gain_correction': [None],
        'sa_correction': [None],
        'equivalent_beam_angle': None,

        # Environmental parameters (USER FILLS IN - REQUIRED)
        'absorption_indicative': None,
        'sound_speed_indicative': None,

        # Physical environment (for calculating sound_speed/absorption)
        'temperature': None,
        'salinity': None,
        'acidity': None,
        'pressure': None,

        # Beam parameters (USER FILLS IN - OPTIONAL)
        'beamwidth_transmit_major': [None],
        'beamwidth_receive_major': [None],
        'beamwidth_transmit_minor': [None],
        'beamwidth_receive_minor': [None],
        'echoangle_major': [None],
        'echoangle_minor': [None],
        'echoangle_major_sensitivity': [None],
        'echoangle_minor_sensitivity': [None],

        # Other parameters (USER FILLS IN - OPTIONAL)
        'sample_interval': None,
        'transmit_bandwidth': None,
        'beam_type': None,
        'calibration_acquisition_method': None,
        'sphere_diameter': None,
        'sphere_material': None,

        # Source file information
        'source_filenames': None,
        'source_file_type': 'manual',
        'source_file_location': None,
        'source_file_paths': None,
        'sonar_software_version': None,
        'sonar_software_name': None,
    }

    return template


def _fmt_yaml_value(val):
    """Format a single value for hand-written YAML output."""
    if val is None:
        return 'null'
    elif isinstance(val, bool):
        return str(val).lower()
    elif isinstance(val, str):
        escaped = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        return f'"{escaped}"'
    else:
        return str(val)


def _fmt_yaml_list(val):
    """Format a list value as YAML flow-style (square brackets)."""
    if val is None or (isinstance(val, list) and len(val) == 0):
        return '[null]'
    if isinstance(val, list):
        return '[' + ', '.join(_fmt_yaml_value(v) for v in val) + ']'
    return '[' + _fmt_yaml_value(val) + ']'


def generate_template_yaml_string(template: dict, calibration_date: str = None) -> str:
    """
    Generate a YAML string with section headers and inline comments for a
    single-channel calibration template file.

    Args:
        template: Calibration template dictionary (from
            :func:`create_calibration_template`).
        calibration_date: Calibration date shown in the instruction header.
            Falls back to ``template['calibration_date']`` when *None*.

    Returns:
        YAML-formatted string suitable for writing to a ``.yaml`` file.
    """
    fmt = _fmt_yaml_value
    fmt_list = _fmt_yaml_list
    t = template
    cal_date = calibration_date or t.get('calibration_date', '')

    yaml_str = f"""# Calibration template
# Auto-generated from raw file channel configurations.
#
# Most parameters use SONAR-netCDF4 v2.1 naming conventions:
# https://htmlpreview.github.io/?https://github.com/ices-publications/SONAR-netCDF4/blob/master/Formatted_docs/crr341.html
#
# YAML formatting guide:
# https://docs.ansible.com/projects/ansible/latest/reference_appendices/YAMLSyntax.html
#
# Instructions:
# 1. Verify calibration date is correct: {cal_date}
# 2. Fill in core calibration values: gain_correction, sa_correction, equivalent_beam_angle
# 3. Fill in environmental parameters OR temperature/salinity/pressure to calculate them
# 4. Fill in beam parameters and optional fields
#
# Do not modify the channel identification parameters at the top
# (transceiver_id, transducer_model, pulse_form, frequency_*, transmit_power,
# transmit_duration_nominal) as these are used for matching to raw files.
#
# Parameter requirements:
#   [MAPPING]  = Required for matching calibration to raw files (do not modify)
#   [REQUIRED] = Required for calibration
#   [OPTIONAL] = Optional
#
# File naming: use a unique name, recommended format:
# YYYY-MM-DD_<frequency in Hz>_<unique configuration id per frequency>

record_created: {fmt(t['record_created'])} # automatically populated when record is created
record_author: {fmt(t['record_author'])} # Name of person or organization who authored this file
channel: {fmt(t['channel'])}  # Channel identifier
transceiver_id: {fmt(t['transceiver_id'])}  # [MAPPING] Transceiver ID for matching
transceiver_model: {fmt(t['transceiver_model'])}  # Transceiver model
transceiver_ethernet_address: {fmt(t['transceiver_ethernet_address'])}
transceiver_serial_number: {fmt(t['transceiver_serial_number'])}
transceiver_number: {fmt(t['transceiver_number'])}
transceiver_port: {fmt(t['transceiver_port'])}
channel_instance_number: {fmt(t['channel_instance_number'])}
transducer_model: {fmt(t['transducer_model'])}  # [MAPPING] Transducer model for matching
transducer_serial_number: {fmt(t['transducer_serial_number'])} # [MAPPING] Ideally provided for mapping, ignored if missing.
pulse_form: {fmt(t['pulse_form'])}  # [MAPPING] Pulse form (0=CW, 1=FM) for matching
frequency_start: {fmt(t['frequency_start'])}  # [MAPPING] Start frequency for matching
frequency_end: {fmt(t['frequency_end'])}  # [MAPPING] End frequency for matching
frequency: {fmt_list(t['frequency'])}
nominal_transducer_frequency: {fmt(t['nominal_transducer_frequency'])}  # Nominal CW operating frequency of transducer (Hz)
transmit_power: {fmt(t['transmit_power'])}  # [MAPPING] Transmit power for matching
transmit_duration_nominal: {fmt(t['transmit_duration_nominal'])}  # [MAPPING] Pulse duration for matching
multiplexing_found: {fmt(t['multiplexing_found'])}

# Calibration metadata
calibration_date: {fmt(t['calibration_date'])}  # [REQUIRED] Date of calibration (YYYY-MM-DD)
calibration_comments: {fmt(t['calibration_comments'])}  # [OPTIONAL] Notes about calibration
calibration_version: {fmt(t['calibration_version'])}  # [OPTIONAL] Calibration version identifier

# Core calibration parameters
gain_correction: {fmt_list(t['gain_correction'])}  # [REQUIRED] Transducer gain correction (dB)
sa_correction: {fmt_list(t['sa_correction'])}  # [REQUIRED] Sa correction factor (dB). Only used in Sv calculation
equivalent_beam_angle: {fmt(t['equivalent_beam_angle'])}  # [REQUIRED] (dB re sr). Only used in Sv calculation

# Environmental parameters
# Option A: Provide sound_speed and absorption directly
# Option B: Provide temperature, salinity, pressure, acidity
absorption_indicative: {fmt(t['absorption_indicative'])}  # [REQUIRED*] Sound absorption coefficient (dB/m) - *or provide T/S/P/acidity
sound_speed_indicative: {fmt(t['sound_speed_indicative'])}  # [REQUIRED*] Sound speed (m/s) - *or provide T/S/P/acidity

# Physical environment (can be used to calculate sound_speed/absorption)
temperature: {fmt(t['temperature'])}  # [OPTIONAL] Water temperature (deg C) - used to calculate sound_speed & absorption
salinity: {fmt(t['salinity'])}  # [OPTIONAL] Water salinity (PSU) - used to calculate sound_speed & absorption
acidity: {fmt(t['acidity'])}  # [OPTIONAL] Water pH (acidity) - used to calculate absorption (default 8.1 if not provided)
pressure: {fmt(t['pressure'])}  # [OPTIONAL] Water pressure (dbar) - used to calculate sound_speed & absorption

# Beam parameters (not currently supported as user parameters in Echopype)
beamwidth_transmit_major: {fmt_list(t['beamwidth_transmit_major'])}  # [REQUIRED] Transmit beamwidth major axis (degrees)
beamwidth_receive_major: {fmt_list(t['beamwidth_receive_major'])}  # [REQUIRED] Receive beamwidth major axis (degrees)
beamwidth_transmit_minor: {fmt_list(t['beamwidth_transmit_minor'])}  # [REQUIRED] Transmit beamwidth minor axis (degrees)
beamwidth_receive_minor: {fmt_list(t['beamwidth_receive_minor'])}  # [REQUIRED] Receive beamwidth minor axis (degrees)
echoangle_major: {fmt_list(t['echoangle_major'])}  # [REQUIRED] Echo angle offset major axis (degrees)
echoangle_minor: {fmt_list(t['echoangle_minor'])}  # [REQUIRED] Echo angle offset minor axis (degrees)
echoangle_major_sensitivity: {fmt_list(t['echoangle_major_sensitivity'])}  # [OPTIONAL] Angle sensitivity major axis
echoangle_minor_sensitivity: {fmt_list(t['echoangle_minor_sensitivity'])}  # [OPTIONAL] Angle sensitivity minor axis

# Optional raw configuration parameters
# sample_interval: Stored per-ping in raw file. Used by echopype to calculate range
# (range = range_sample * sample_interval * sound_speed / 2). Not needed for mapping.
sample_interval: {fmt(t['sample_interval'])}

# transmit_bandwidth: Derived from other parameters. For CW: function of pulse duration
# and frequency. For FM: approximately (frequency_end - frequency_start).
transmit_bandwidth: {fmt(t['transmit_bandwidth'])}

# Calibration provenance
calibration_acquisition_method: {fmt(t['calibration_acquisition_method'])}  # [OPTIONAL] Method (e.g., sphere, in-situ)
sphere_diameter: {fmt(t['sphere_diameter'])}  # [OPTIONAL] Calibration sphere diameter (mm)
sphere_material: {fmt(t['sphere_material'])}  # [OPTIONAL] Sphere material (e.g., tungsten carbide, copper)
beam_type: {fmt(t['beam_type'])}  # [OPTIONAL] Beam type
source_filenames: {fmt(t['source_filenames'])}  # [OPTIONAL] Source calibration filenames
source_file_type: {fmt(t['source_file_type'])}
source_file_location: {fmt(t['source_file_location'])}  # [OPTIONAL] Location of source files
source_file_paths: {fmt(t['source_file_paths'])}  # [OPTIONAL] Full paths to source files
sonar_software_version: {fmt(t['sonar_software_version'])}  # [OPTIONAL] Sonar software version during calibration
sonar_software_name: {fmt(t['sonar_software_name'])}  # [OPTIONAL] Sonar software name
"""
    return yaml_str


def save_template_with_comments(template: dict, file_path, calibration_date: str = None):
    """
    Save a calibration template to a YAML file with section headers and
    inline comments.

    Args:
        template: Calibration template dictionary.
        file_path: Destination file path (str or Path).
        calibration_date: Calibration date shown in the instruction header.
            Falls back to ``template['calibration_date']`` when *None*.
    """
    file_path = Path(file_path)
    yaml_str = generate_template_yaml_string(template, calibration_date)
    with open(file_path, 'w') as f:
        f.write(yaml_str)


def generate_channel_section_yaml(channel_key: str, template: dict) -> str:
    """
    Generate a YAML section for one channel with inline comments, suitable
    for inclusion in a multi-channel calibration configurations file.

    Args:
        channel_key: The unique key for this channel configuration.
        template: Calibration template dictionary.

    Returns:
        YAML-formatted string for one channel section.
    """
    fmt = _fmt_yaml_value
    fmt_list = _fmt_yaml_list
    t = template
    ind = "  "  # base indent for values under channel key

    section = f"""{channel_key}:
{ind}record_created: {fmt(t['record_created'])}
{ind}record_author: {fmt(t['record_author'])}
{ind}channel: {fmt(t['channel'])}  # [MAPPING] Channel identifier
{ind}transceiver_id: {fmt(t['transceiver_id'])}  # [MAPPING] Transceiver ID
{ind}transceiver_model: {fmt(t['transceiver_model'])}
{ind}transceiver_ethernet_address: {fmt(t['transceiver_ethernet_address'])}
{ind}transceiver_serial_number: {fmt(t['transceiver_serial_number'])}
{ind}transceiver_number: {fmt(t['transceiver_number'])}
{ind}transceiver_port: {fmt(t['transceiver_port'])}
{ind}channel_instance_number: {fmt(t['channel_instance_number'])}
{ind}transducer_model: {fmt(t['transducer_model'])}  # [MAPPING] Transducer model
{ind}transducer_serial_number: {fmt(t['transducer_serial_number'])}
{ind}pulse_form: {fmt(t['pulse_form'])}  # [MAPPING] Pulse form (0=CW, 1=FM)
{ind}frequency_start: {fmt(t['frequency_start'])}  # [MAPPING] Start frequency
{ind}frequency_end: {fmt(t['frequency_end'])}  # [MAPPING] End frequency
{ind}frequency: {fmt_list(t['frequency'])}
{ind}nominal_transducer_frequency: {fmt(t['nominal_transducer_frequency'])}  # Nominal CW frequency (Hz)
{ind}transmit_power: {fmt(t['transmit_power'])}  # [MAPPING] Transmit power
{ind}transmit_duration_nominal: {fmt(t['transmit_duration_nominal'])}  # [MAPPING] Pulse duration
{ind}multiplexing_found: {fmt(t['multiplexing_found'])}
{ind}# --- CALIBRATION METADATA ---
{ind}calibration_date: {fmt(t['calibration_date'])}  # [REQUIRED] Date (YYYY-MM-DD)
{ind}calibration_comments: {fmt(t['calibration_comments'])}  # [OPTIONAL]
{ind}calibration_version: {fmt(t['calibration_version'])}  # [OPTIONAL]
{ind}# --- CORE CALIBRATION (REQUIRED for Sv/TS) ---
{ind}gain_correction: {fmt_list(t['gain_correction'])}  # [REQUIRED] Gain correction (dB)
{ind}sa_correction: {fmt_list(t['sa_correction'])}  # [REQUIRED-Sv] Sa correction (dB)
{ind}equivalent_beam_angle: {fmt(t['equivalent_beam_angle'])}  # [REQUIRED-Sv] (dB re 1 sr)
{ind}# --- ENVIRONMENTAL (provide directly OR use T/S/P/acidity) ---
{ind}absorption_indicative: {fmt(t['absorption_indicative'])}  # [REQUIRED*] dB/m
{ind}sound_speed_indicative: {fmt(t['sound_speed_indicative'])}  # [REQUIRED*] m/s
{ind}# --- PHYSICAL ENVIRONMENT (for calculating sound_speed/absorption) ---
{ind}temperature: {fmt(t['temperature'])}  # [ECHOPYPE-ENV] deg C
{ind}salinity: {fmt(t['salinity'])}  # [ECHOPYPE-ENV] PSU
{ind}acidity: {fmt(t['acidity'])}  # [ECHOPYPE-ENV] pH (acidity)
{ind}pressure: {fmt(t['pressure'])}  # [ECHOPYPE-ENV] dbar
{ind}# --- BEAM PARAMETERS (EK80 broadband only) ---
{ind}beamwidth_transmit_major: {fmt_list(t['beamwidth_transmit_major'])}
{ind}beamwidth_receive_major: {fmt_list(t['beamwidth_receive_major'])}
{ind}beamwidth_transmit_minor: {fmt_list(t['beamwidth_transmit_minor'])}
{ind}beamwidth_receive_minor: {fmt_list(t['beamwidth_receive_minor'])}
{ind}echoangle_major: {fmt_list(t['echoangle_major'])}
{ind}echoangle_minor: {fmt_list(t['echoangle_minor'])}
{ind}echoangle_major_sensitivity: {fmt_list(t['echoangle_major_sensitivity'])}
{ind}echoangle_minor_sensitivity: {fmt_list(t['echoangle_minor_sensitivity'])}
{ind}# --- OPTIONAL PARAMETERS ---
{ind}sample_interval: {fmt(t['sample_interval'])}
{ind}transmit_bandwidth: {fmt(t['transmit_bandwidth'])}
{ind}calibration_acquisition_method: {fmt(t['calibration_acquisition_method'])}
{ind}sphere_diameter: {fmt(t['sphere_diameter'])}
{ind}sphere_material: {fmt(t['sphere_material'])}
{ind}beam_type: {fmt(t['beam_type'])}
{ind}source_filenames: {fmt(t['source_filenames'])}
{ind}source_file_type: {fmt(t['source_file_type'])}
{ind}source_file_location: {fmt(t['source_file_location'])}
{ind}source_file_paths: {fmt(t['source_file_paths'])}
{ind}sonar_software_version: {fmt(t['sonar_software_version'])}
{ind}sonar_software_name: {fmt(t['sonar_software_name'])}
"""
    return section


def save_multi_channel_config_with_comments(templates: dict, file_path):
    """
    Save a multi-channel calibration configurations file with section
    headers and inline comments for each channel.

    Args:
        templates: Dictionary mapping channel_key -> template dict.
        file_path: Destination file path (str or Path).
    """
    file_path = Path(file_path)
    header = """# Calibration configurations
# This file contains all calibration templates in a single file.
# You can edit either this file or the individual files in:
#   Single_Channel_Calibration_Templates/
#
# After filling in values, run Step 6 to generate final mapping files.
#
# Parameter key:
#   [MAPPING]    = Do not modify (used for matching)
#   [REQUIRED]   = Required for Sv/TS calibration
#   [REQUIRED*]  = Required OR provide T/S/P/acidity instead
#   [OPTIONAL]   = Optional metadata

"""
    with open(file_path, 'w') as f:
        f.write(header)
        for channel_key, template in templates.items():
            section = generate_channel_section_yaml(channel_key, template)
            f.write(section)
            f.write("\n")  # blank line between channels


def load_calibration_templates(template_dir) -> dict:
    """
    Load all calibration template ``.yaml`` (or ``.yml``) files from a directory.

    Args:
        template_dir: Path to the directory containing template files.

    Returns:
        Dictionary mapping template_key (filename stem) -> template_data.
    """
    template_dir = Path(template_dir)
    templates = {}
    for template_file in sorted(
        list(template_dir.glob("*.yaml")) + list(template_dir.glob("*.yml"))
    ):
        with open(template_file, 'r') as f:
            template = yaml.safe_load(f)
        # Extract key from filename stem (works for both .yaml and .yml)
        key = template_file.stem
        templates[key] = template
    return templates


def check_required_fields(template: dict) -> list:
    """
    Check if required calibration fields are filled in.

    Args:
        template: A calibration template dictionary.

    Returns:
        List of unfilled required field names. An empty list means
        all required fields are present.
    """
    unfilled = []

    # Check calibration date
    cal_date = template.get('calibration_date')
    if cal_date is None or cal_date == 'YYYY-MM-DD':
        unfilled.append('calibration_date')

    # Check core calibration values
    gain = template.get('gain_correction', [None])
    if gain is None or (isinstance(gain, list) and (len(gain) == 0 or gain[0] is None)):
        unfilled.append('gain_correction')

    sa = template.get('sa_correction', [None])
    if sa is None or (isinstance(sa, list) and (len(sa) == 0 or sa[0] is None)):
        unfilled.append('sa_correction')

    eba = template.get('equivalent_beam_angle')
    if eba is None:
        unfilled.append('equivalent_beam_angle')

    # Check environmental parameters
    if template.get('absorption_indicative') is None:
        unfilled.append('absorption_indicative')

    if template.get('sound_speed_indicative') is None:
        unfilled.append('sound_speed_indicative')

    return unfilled


def generate_calibration_templates(
    unique_channels: dict,
    calibration_date: str,
    record_author: str,
    output_dir,
    short_filenames: bool = False,
) -> dict:
    """Generate calibration template files from unique channel configurations.

    Creates one template ``.yaml`` file per unique channel, with null values
    for the user to fill in. All templates share the same ``record_created``
    timestamp.

    Args:
        unique_channels: Dictionary mapping channel_key -> channel_data
            (as returned by :func:`~aa_si_calibration.raw_reader_api.extract_unique_channels`).
        calibration_date: Calibration date string (``YYYY-MM-DD``).
        record_author: Author name to embed in each template.
        output_dir: Directory to write the individual ``.yaml`` files.
        short_filenames: If True, use compact ``<date>_<freq>_config-<N>``
            naming; otherwise use long key-derived names.

    Returns:
        Dictionary mapping channel_key -> template dict (keyed by short
        keys when *short_filenames* is True).
    """
    import datetime as _dt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

    # Build filename mapping
    if short_filenames:
        filename_map = build_short_filename_map(unique_channels, calibration_date=calibration_date)
    else:
        filename_map = {k: calibration_key_to_filename(k) for k in unique_channels}

    # Generate templates
    calibration_templates = {}
    for channel_key, channel in unique_channels.items():
        template = create_calibration_template(channel, calibration_date)
        template['record_created'] = batch_timestamp
        template['record_author'] = record_author
        calibration_templates[channel_key] = template

        safe_name = filename_map[channel_key]
        template_file = output_dir / f"{safe_name}.yaml"
        save_template_with_comments(template, template_file, calibration_date)

    # Remap to short keys if requested
    if short_filenames:
        calibration_templates = {
            filename_map[k]: v for k, v in calibration_templates.items()
        }
        print_short_key_summary(filename_map, {k: unique_channels[k] for k in filename_map})

    print(f"\nGenerated {len(calibration_templates)} calibration template file(s)")
    print(f"  Output directory: {output_dir}")
    print(f"  Filename style: {'short' if short_filenames else 'long'}")
    print(f"  Record created: {batch_timestamp}")
    print(f"  Record author: {record_author}")
    print("\nTemplate files created:")
    for template_file in sorted(output_dir.glob("*.yaml")):
        print(f"  - {template_file.name}")

    return calibration_templates


def validate_loaded_templates(
    template_dir,
) -> tuple:
    """Load calibration templates and check each one for completeness.

    Args:
        template_dir: Directory containing calibration template ``.yaml`` files.

    Returns:
        Tuple of ``(loaded_templates, all_complete)`` where
        *loaded_templates* is a ``{key: template_dict}`` mapping and
        *all_complete* is True when every required field is filled.
    """
    loaded_templates = load_calibration_templates(template_dir)

    print(f"Loaded {len(loaded_templates)} calibration template(s)")
    print("=" * 80)

    all_complete = True
    for template_key, template in loaded_templates.items():
        unfilled = check_required_fields(template)
        channel = template.get('channel', 'Unknown')

        if unfilled:
            all_complete = False
            print(f"\n  WARNING: {channel}")
            print(f"   Missing required fields: {', '.join(unfilled)}")
        else:
            print(f"\n  OK: {channel}")
            print(f"   All required fields filled")
            print(f"   Calibration date: {template.get('calibration_date')}")
            print(f"   Gain: {template.get('gain_correction')}, Sa: {template.get('sa_correction')}")

    if not all_complete:
        print("\n" + "=" * 80)
        print("WARNING: Some templates have missing required fields.")
        print("Fill in the missing values before using the calibration data.")
    else:
        print("\n" + "=" * 80)
        print("All calibration templates are complete!")

    return loaded_templates, all_complete

