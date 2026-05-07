"""Calibration template generation, loading, and validation.

Provides functions for creating calibration template files from raw channel
configurations, saving them as commented YAML, loading and validating
user-filled templates, and generating multi-channel configuration files.
"""

from pathlib import Path
import yaml

from .calibration_keys import (
    calibration_key_to_filename,
    build_short_filename_map,
    print_short_key_summary,
)


def create_calibration_template(channel: dict, calibration_date: str) -> dict:
    """Create a calibration template from a raw file channel configuration.

    Pre-fills channel identification parameters and leaves calibration values
    as None for the user to fill in.

    Args:
        channel: Raw channel configuration dictionary (as returned by the
            raw reader extraction functions).
        calibration_date: Calibration date string (YYYY-MM-DD).

    Returns:
        Template dictionary ready for serialization.
    """
    transmit_duration = round(channel.get('transmit_duration_nominal', 0), 6)

    template = {
        'record_created': None,
        'record_author': None,
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
        'calibration_date': calibration_date,
        'calibration_comments': None,
        'calibration_version': None,
        'gain_correction': [None],
        'sa_correction': [None],
        'equivalent_beam_angle': None,
        'absorption_indicative': None,
        'sound_speed_indicative': None,
        'temperature': None,
        'salinity': None,
        'acidity': None,
        'pressure': None,
        'beamwidth_transmit_major': [None],
        'beamwidth_receive_major': [None],
        'beamwidth_transmit_minor': [None],
        'beamwidth_receive_minor': [None],
        'echoangle_major': [None],
        'echoangle_minor': [None],
        'echoangle_major_sensitivity': [None],
        'echoangle_minor_sensitivity': [None],
        'sample_interval': None,
        'transmit_bandwidth': None,
        'beam_type': None,
        'calibration_acquisition_method': None,
        'sphere_diameter': None,
        'sphere_material': None,
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
    """Generate a YAML string with section headers and inline comments.

    Args:
        template: Calibration template dictionary.
        calibration_date: Calibration date shown in the instruction header.
            Falls back to ``template['calibration_date']`` when None.

    Returns:
        YAML-formatted string suitable for writing to a .yaml file.
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
    """Save a calibration template to a YAML file with inline comments.

    Args:
        template: Calibration template dictionary.
        file_path: Destination file path.
        calibration_date: Calibration date shown in the instruction header.
    """
    file_path = Path(file_path)
    yaml_str = generate_template_yaml_string(template, calibration_date)
    with open(file_path, 'w') as f:
        f.write(yaml_str)


def generate_channel_section_yaml(channel_key: str, template: dict) -> str:
    """Generate a YAML section for one channel in a multi-channel file.

    Args:
        channel_key: The unique key for this channel configuration.
        template: Calibration template dictionary.

    Returns:
        YAML-formatted string for one channel section.
    """
    fmt = _fmt_yaml_value
    fmt_list = _fmt_yaml_list
    t = template
    ind = "  "

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
{ind}# Calibration metadata
{ind}calibration_date: {fmt(t['calibration_date'])}  # [REQUIRED] Date (YYYY-MM-DD)
{ind}calibration_comments: {fmt(t['calibration_comments'])}  # [OPTIONAL]
{ind}calibration_version: {fmt(t['calibration_version'])}  # [OPTIONAL]
{ind}# Core calibration (required for Sv/TS)
{ind}gain_correction: {fmt_list(t['gain_correction'])}  # [REQUIRED] Gain correction (dB)
{ind}sa_correction: {fmt_list(t['sa_correction'])}  # [REQUIRED-Sv] Sa correction (dB)
{ind}equivalent_beam_angle: {fmt(t['equivalent_beam_angle'])}  # [REQUIRED-Sv] (dB re 1 sr)
{ind}# Environmental (provide directly OR use T/S/P/acidity)
{ind}absorption_indicative: {fmt(t['absorption_indicative'])}  # [REQUIRED*] dB/m
{ind}sound_speed_indicative: {fmt(t['sound_speed_indicative'])}  # [REQUIRED*] m/s
{ind}# Physical environment (for calculating sound_speed/absorption)
{ind}temperature: {fmt(t['temperature'])}  # [ECHOPYPE-ENV] deg C
{ind}salinity: {fmt(t['salinity'])}  # [ECHOPYPE-ENV] PSU
{ind}acidity: {fmt(t['acidity'])}  # [ECHOPYPE-ENV] pH (acidity)
{ind}pressure: {fmt(t['pressure'])}  # [ECHOPYPE-ENV] dbar
{ind}# Beam parameters
{ind}beamwidth_transmit_major: {fmt_list(t['beamwidth_transmit_major'])}
{ind}beamwidth_receive_major: {fmt_list(t['beamwidth_receive_major'])}
{ind}beamwidth_transmit_minor: {fmt_list(t['beamwidth_transmit_minor'])}
{ind}beamwidth_receive_minor: {fmt_list(t['beamwidth_receive_minor'])}
{ind}echoangle_major: {fmt_list(t['echoangle_major'])}
{ind}echoangle_minor: {fmt_list(t['echoangle_minor'])}
{ind}echoangle_major_sensitivity: {fmt_list(t['echoangle_major_sensitivity'])}
{ind}echoangle_minor_sensitivity: {fmt_list(t['echoangle_minor_sensitivity'])}
{ind}# Optional parameters
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
    """Save a multi-channel calibration configurations file.

    Args:
        templates: Dictionary mapping channel_key -> template dict.
        file_path: Destination file path.
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
            f.write("\n")


def load_calibration_templates(template_dir) -> dict:
    """Load all calibration template .yaml/.yml files from a directory.

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
        key = template_file.stem
        templates[key] = template
    return templates


def check_required_fields(template: dict) -> list:
    """Check if required calibration fields are filled in.

    Args:
        template: A calibration template dictionary.

    Returns:
        List of unfilled required field names. Empty list means all present.
    """
    unfilled = []

    cal_date = template.get('calibration_date')
    if cal_date is None or cal_date == 'YYYY-MM-DD':
        unfilled.append('calibration_date')

    gain = template.get('gain_correction', [None])
    if gain is None or (isinstance(gain, list) and (len(gain) == 0 or gain[0] is None)):
        unfilled.append('gain_correction')

    sa = template.get('sa_correction', [None])
    if sa is None or (isinstance(sa, list) and (len(sa) == 0 or sa[0] is None)):
        unfilled.append('sa_correction')

    if template.get('equivalent_beam_angle') is None:
        unfilled.append('equivalent_beam_angle')

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

    Creates one template .yaml file per unique channel, with null values
    for the user to fill in.

    Args:
        unique_channels: Dictionary mapping channel_key -> channel_data.
        calibration_date: Calibration date string (YYYY-MM-DD).
        record_author: Author name to embed in each template.
        output_dir: Directory to write the individual .yaml files.
        short_filenames: If True, use compact naming.

    Returns:
        Dictionary mapping channel_key -> template dict.
    """
    import datetime as _dt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if short_filenames:
        filename_map = build_short_filename_map(unique_channels, calibration_date=calibration_date)
    else:
        filename_map = {k: calibration_key_to_filename(k) for k in unique_channels}

    calibration_templates = {}
    for channel_key, channel in unique_channels.items():
        template = create_calibration_template(channel, calibration_date)
        template['record_created'] = batch_timestamp
        template['record_author'] = record_author
        calibration_templates[channel_key] = template

        safe_name = filename_map[channel_key]
        template_file = output_dir / f"{safe_name}.yaml"
        save_template_with_comments(template, template_file, calibration_date)

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


def validate_loaded_templates(template_dir) -> tuple:
    """Load calibration templates and check each one for completeness.

    Args:
        template_dir: Directory containing calibration template .yaml files.

    Returns:
        Tuple of (loaded_templates, all_complete) where loaded_templates is a
        {key: template_dict} mapping and all_complete is True when every
        required field is filled.
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
