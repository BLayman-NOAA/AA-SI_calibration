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
    TRANSDUCER_SERIAL_UNKNOWN,
)
from .utils import extract_nominal_frequency_from_transducer_model

# Functions that have been moved to dedicated modules but are re-exported
# here for backward compatibility.
from .calibration_keys import (  # noqa: F401
    extract_serial_number_from_channel_name,
    extract_channel_components,
    build_calibration_key,
    calibration_key_to_filename,
    build_short_filename_map,
    remap_to_short_keys,
    print_short_key_summary,
    _round_key_field,
    _get_nominal_frequency_hz,
    _KEY_FIELD_PRECISIONS,
)
from .templates import (  # noqa: F401
    create_calibration_template,
    save_template_with_comments,
    generate_template_yaml_string,
    generate_channel_section_yaml,
    save_multi_channel_config_with_comments,
    load_calibration_templates,
    check_required_fields,
    generate_calibration_templates,
    validate_loaded_templates,
)


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


def _normalize_date_to_iso8601(date_value):
    """Convert date strings like MM/DD/YYYY to ISO 8601 format (YYYY-MM-DD).

    Handles common formats: MM/DD/YYYY, M/D/YYYY, MM-DD-YYYY, M-D-YYYY.
    Returns the original value if already in ISO format or cannot be parsed.
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
                    if 1 <= month <= 12 and 1 <= day <= 31 and year >= 1900:
                        return f"{year:04d}-{month:02d}-{day:02d}"
                except ValueError:
                    pass

    return date_value


def _normalize_source_list(raw_value):
    """Normalize source filenames to a list of strings, or None."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple, np.ndarray)):
        normalized = [str(item) for item in raw_value if item is not None]
        return normalized or None
    return [str(raw_value)]


def _normalize_source_location(raw_value):
    """Normalize source file location to a comma-separated string, or None."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple, np.ndarray)):
        normalized = [str(item) for item in raw_value if item is not None]
        return ", ".join(normalized) if normalized else None
    return str(raw_value)


def _normalize_path_list(raw_value):
    """Normalize file paths to a list of strings, or None."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple, np.ndarray)):
        normalized = [str(item) for item in raw_value if item is not None]
        return normalized or None
    return [str(raw_value)]


def _resolve_source_file_type(raw_value, index):
    """Resolve the source file type for a given channel index."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple, np.ndarray)):
        try:
            candidate = raw_value[index]
        except (IndexError, TypeError):
            candidate = None
        return str(candidate) if candidate is not None else None
    return str(raw_value)


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

    normalized_location = _normalize_source_location(source_file_location_data)
    normalized_paths = _normalize_path_list(source_file_paths_data)
    
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
            channel_payload["calibration_date"] = _normalize_date_to_iso8601(channel_payload["calibration_date"])

        channel_payload["source_filenames"] = _normalize_source_list(channel_sources)
        channel_payload["source_file_type"] = _resolve_source_file_type(source_file_type_data, idx)
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


def _strip_internal_keys(data: dict) -> dict:
    """Return a copy of *data* with internal tracking keys removed.

    Internal keys start with ``_`` (e.g. ``_calibration_file_key``).
    """
    return {k: v for k, v in data.items() if not k.startswith('_')}


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

