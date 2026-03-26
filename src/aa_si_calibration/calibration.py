# imports and variables
import echopype as ep 
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import json
import os
import re

from aa_si_calibration.raw_reader_api import process_raw_folder, save_yaml
from aa_si_calibration import manufacturer_file_parsers
from aa_si_calibration import standardized_file_lib
from aa_si_calibration.mapping_algorithm import (
    load_raw_configs,
    load_calibration_data_from_single_files,
    build_mapping,
    save_mapping_files,
    print_mapping_preview,
    handle_unused_calibration_files,
    resolve_conflicts_interactive,
    check_for_conflicts,
    check_required_calibration_params,
    verify_calibration_file_usage,
)
from aa_si_calibration.standardized_file_lib import (
    remap_to_short_keys,
    print_short_key_summary,
    calibration_key_to_filename,
)
import yaml



def get_pulse_length_indicies(transmit_duration, pulse_length_table):
    """Find indices for pulse lengths that match transmit durations within tolerance.
    
    Args:
        transmit_duration: Array of transmit durations for each frequency
        pulse_length_table: 2D table of pulse lengths organized by frequency and pulse length
        
    Returns:
        list: Indices of matching pulse lengths for each frequency
    """
    indicies = []
    # for every row in table
    for i in range(len(pulse_length_table)):
        frequency_list = pulse_length_table[i]
        # check for match with corresponding transmit duration at that frequency
        for k in range(len(frequency_list)):
            pulse_length = frequency_list[k]
            if(abs(pulse_length - transmit_duration[i]) < .000001):
                # append indicies of matches
                indicies.append(k)
                break
    return indicies


def check_parameter_changes(parameter_data, parameter_name, channels, changes, flags):
    """Helper function to check for parameter changes across pings and channels.
    
    Args:
        parameter_data: 2D array of parameter values [channel][ping]
        parameter_name: Name of the parameter being checked
        channels: Array of channel names
        changes: List to append change info to
        flags: Dictionary to append change info to
    """
    if parameter_data is not None:
        for ch_idx in range(len(parameter_data)):
            for i in range(1, len(parameter_data[ch_idx])):
                if parameter_data[ch_idx][i] != parameter_data[ch_idx][i-1]:
                    change_info = {
                        "parameter": parameter_name,
                        "ping_index": i,
                        "channel": channels[ch_idx] if channels is not None else f"channel_{ch_idx}",
                        "value_before": parameter_data[ch_idx][i-1],
                        "value_after": parameter_data[ch_idx][i]
                    }
                    changes.append(change_info)
                    flags["data_irregularities"]["across_pings"].append(change_info)
                    # TODO: print change_info in human readable format:
                    print(f"WARNING: \nParameter '{change_info['parameter']}' changed on {change_info['channel']} "
                          f"at ping {change_info['ping_index']}: "
                          f"{change_info['value_before']} -> {change_info['value_after']}")


def extract_netcdf_calibration_parameters(echodata, output_logs_folder):
    """Extract calibration and environmental parameters from echopype netCDF data.
    
    This function extracts various calibration parameters that are supported by echopype,
    including environmental parameters (sound speed, absorption) and calibration parameters
    (gain correction, SA correction, equivalent beam angle).
    
    Args:
        echodata: Echopype EchoData object containing sonar data
        output_logs_folder: Path to folder for saving log files
        
    Returns:
        dict: Dictionary containing:
            - env_params: Environmental parameters (sound_speed, sound_absorption)
            - cal_params: Calibration parameters (gain_correction, sa_correction, equivalent_beam_angle)
            - other_params: Other parameters (channels, transmit_duration, frequency_nominal)
            - channels: Array of channel names
    """
    # Ensure output folder exists
    os.makedirs(output_logs_folder, exist_ok=True)
    
    # Load or create calibration flags JSON
    flags_file = Path(output_logs_folder) / "calibration_flags.json"
    if flags_file.exists():
        with open(flags_file, 'r') as f:
            flags = json.load(f)
    else:
        flags = {
            "moderate_impacts": [],
            "large_impacts": [],
            "critical_impacts": [],
            "data_irregularities": {
                "across_frequencies": [],
                "across_pings": []
            },
            "missing_parameters": []
        }
    
    # Ensure all required keys exist
    for key in ["moderate_impacts", "large_impacts", "critical_impacts", "data_irregularities", "missing_parameters"]:
        if key not in flags:
            flags[key] = []
        if key == "data_irregularities":
            if "across_frequencies" not in flags[key]:
                flags[key]["across_frequencies"] = []
            if "across_pings" not in flags[key]:
                flags[key]["across_pings"] = []

    # NOTE: parameters supported by Echopype:

    # env_params: 
    #   sound speed, 
    #   absorption, 
    #   or precursors to calculate: temperature, salinity, and pressure

    # cal_params: 
    #    sa_correction, 
    #    gain_correction, 
    #    equivalent_beam_angle, 
    #    angle_offset_alongship,
    #    angle_offset_athwartship,
    #    angle_sensitivity_alongship,
    #    angle_sensitivity_athwartship,
    #    beamwidth_alongship,
    #    beamwidth_athwartship,
    #    default params: impedance_transducer, impedance_transceiver, receiver_sampling_frequency

    # see get_env_params_EK and get_cal_params_EK in cal_params.py


    # TODO: 
    # Transducer Name (beam group)

    # Transceiver:
    # Receiver Bandwidth

    # Sound Speed
    try:
        sound_speed_num = echodata["Environment"].sound_speed_indicative.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Environment/sound_speed_indicative")
        sound_speed_num = None

    # Absorption
    try:
        absorption_num = echodata["Environment"].absorption_indicative.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Environment/absorption_indicative")
        absorption_num = None

    # transmit duration
    try:
        transmit_duration_num = echodata["Sonar/Beam_group1"].transmit_duration_nominal.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/transmit_duration_nominal")
        transmit_duration_num = None

    try:
        pulse_length_table = echodata["Vendor_specific"].pulse_length.values
        pulse_length_indicies = get_pulse_length_indicies(transmit_duration_num[:,0], pulse_length_table)
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Vendor_specific/pulse_length")
        pulse_length_table = None
        pulse_length_indicies = None


    # gain correction
    try:
        gain_correction_table = echodata["Vendor_specific"].gain_correction.values
        gain_correction_num = [gain_correction_table[i][pulse_length_indicies[i]] for i in range(len(gain_correction_table))]
    except (KeyError, AttributeError, IndexError):
        flags["missing_parameters"].append("Vendor_specific/gain_correction")
        gain_correction_num = None

    # sa correction
    try:
        sa_correction_table = echodata["Vendor_specific"].sa_correction.values
        sa_correction_num = [sa_correction_table[i][pulse_length_indicies[i]] for i in range(len(sa_correction_table))]
    except (KeyError, AttributeError, IndexError):
        flags["missing_parameters"].append("Vendor_specific/sa_correction")
        sa_correction_num = None
        
    # equivalent_beam_angle
    try:
        equivalent_beam_angle_num = echodata["Sonar/Beam_group1"].equivalent_beam_angle.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/equivalent_beam_angle")
        equivalent_beam_angle_num = None

    # channels (Transceivers)
    try:
        channels = echodata["Sonar/Beam_group1"].channel.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/channel")
        channels = None

    # frequencies
    try:
        frequency_nominal = echodata["Sonar/Beam_group1"].frequency_nominal.values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/frequency_nominal")
        frequency_nominal = None

    try:
        sonar_software_version = echodata["Sonar"].sonar_software_version
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/sonar_software_version")
        sonar_software_version = None

    try:
        beamwidth_twoway_athwartship = echodata["Sonar/Beam_group1"]["beamwidth_twoway_athwartship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/beamwidth_twoway_athwartship")
        beamwidth_twoway_athwartship = None

    try:
        beamwidth_twoway_alongship = echodata["Sonar/Beam_group1"]["beamwidth_twoway_alongship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/beamwidth_twoway_alongship")
        beamwidth_twoway_alongship = None

    try:
        angle_offset_athwartship = echodata["Sonar/Beam_group1"]["angle_offset_athwartship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/angle_offset_athwartship")
        angle_offset_athwartship = None

    try:
        angle_offset_alongship = echodata["Sonar/Beam_group1"]["angle_offset_alongship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/angle_offset_alongship")
        angle_offset_alongship = None

    try:
        angle_sensitivity_athwartship = echodata["Sonar/Beam_group1"]["angle_sensitivity_athwartship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/angle_sensitivity_athwartship")
        angle_sensitivity_athwartship = None

    try:
        angle_sensitivity_alongship = echodata["Sonar/Beam_group1"]["angle_sensitivity_alongship"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/angle_sensitivity_alongship")
        angle_sensitivity_alongship = None

    try:
        sample_interval = echodata["Sonar/Beam_group1"]["sample_interval"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/sample_interval")
        sample_interval = None

    try:
        transmit_power = echodata["Sonar/Beam_group1"]["transmit_power"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/transmit_power")
        transmit_power = None

    try:
        transmit_bandwidth = echodata["Sonar/Beam_group1"]["transmit_bandwidth"].values
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Sonar/Beam_group1/transmit_bandwidth")
        transmit_bandwidth = None

    # Log missing parameters
    for param in flags["missing_parameters"]:
        print(f"Missing parameter: {param}")

    # flag differences across sound speed frequencies at first ping 
    if sound_speed_num is not None and frequency_nominal is not None:
        if not all(f == sound_speed_num[0][0] for f in sound_speed_num[:, 0]):
            print("Warning: Different sound speed values detected across frequencies:")
            for i in range(len(sound_speed_num)):
                print(f"  - Frequency {frequency_nominal[i]} Hz: sound speed = {sound_speed_num[i][0]} m/s")
                flags["data_irregularities"]["across_frequencies"].append(f"Different sound speed values across frequencies: {frequency_nominal[i]} Hz has {sound_speed_num[i][0]} m/s")

    # check for change in parameters across pings and log to JSON
    changes = []

    # Use helper function for each parameter
    check_parameter_changes(sample_interval, "sample_interval", channels, changes, flags)
    check_parameter_changes(transmit_duration_num, "transmit_duration", channels, changes, flags)
    check_parameter_changes(transmit_power, "transmit_power", channels, changes, flags)
    check_parameter_changes(transmit_bandwidth, "transmit_bandwidth", channels, changes, flags)
    check_parameter_changes(absorption_num, "absorption", channels, changes, flags)
    check_parameter_changes(sound_speed_num, "sound_speed", channels, changes, flags)

    # Save updated flags to JSON
    with open(flags_file, 'w') as f:
        json.dump(flags, f, indent=2)

    # Process parameters for return (handle None values)
    if sound_speed_num is not None:
        sound_speed_num = sound_speed_num[0][0]
    if absorption_num is not None:
        absorption_num = absorption_num[:, 0]
    if transmit_duration_num is not None:
        transmit_duration_num = transmit_duration_num[:, 0]
    if sample_interval is not None:
        sample_interval = sample_interval[:, 0]
    if transmit_power is not None:
        transmit_power = transmit_power[:, 0]
    if transmit_bandwidth is not None:
        transmit_bandwidth = transmit_bandwidth[:, 0]

    env_params = {
        "sound_speed": sound_speed_num,
        "sound_absorption": absorption_num
    }

    cal_params = {
        "gain_correction": gain_correction_num,
        "sa_correction": sa_correction_num,
        "equivalent_beam_angle": equivalent_beam_angle_num,
        "beamwidth_athwartship": beamwidth_twoway_athwartship,
        "beamwidth_alongship": beamwidth_twoway_alongship,
        "angle_offset_athwartship": angle_offset_athwartship,
        "angle_offset_alongship": angle_offset_alongship,
        "angle_sensitivity_athwartship": angle_sensitivity_athwartship,
        "angle_sensitivity_alongship": angle_sensitivity_alongship
    }

    other_params = {
        "channel": channels,
        "transmit_duration_nominal": transmit_duration_num,
        "frequency_nominal": frequency_nominal,
        "sample_interval": sample_interval,
        "transmit_power": transmit_power,
        "sonar_software_version": sonar_software_version,
        "transmit_bandwidth": transmit_bandwidth
    }

    return {
        "env_params" : env_params,
        "cal_params" : cal_params,
        "other_params" : other_params,
        "channel" : channels
    }


def extract_standardized_calibration_parameters(
    calibration_dict, mapping_dict, filename=None, echodata=None,
):
    """Extract standardized calibration parameters in the comparison format.

    Reverses the per-channel standardized format stored in *calibration_dict*
    back into the ``(cal_params, env_params, other_params)`` structure used by
    :func:`comparison.run_full_calibration_comparison` and
    :func:`print_calibration_values`.

    This is the inverse of
    :func:`standardized_file_lib.convert_params_to_standardized_names`.

    Args:
        calibration_dict: ``{cal_key: {standardized_param: value, …}, …}``
            as returned by :func:`generate_standardized_cal_mapping`.
        mapping_dict: ``{filename: {channel_id: cal_key, …}, …}``
            as returned by :func:`generate_standardized_cal_mapping`.
        filename: Raw filename whose channels to extract.  If *None*, the
            first filename in *mapping_dict* is used.
        echodata: Optional EchoData object.  If provided, channel ordering
            is taken from ``echodata["Sonar/Beam_group1"].channel.values``
            to guarantee alignment with echopype arrays.

    Returns:
        dict with keys ``cal_params``, ``env_params``, ``other_params``.
    """
    if filename is None:
        filename = next(iter(mapping_dict))

    file_channels = mapping_dict[filename]

    # Determine channel ordering
    if echodata is not None:
        ordered_channel_ids = list(echodata["Sonar/Beam_group1"].channel.values)
    else:
        ordered_channel_ids = list(file_channels.keys())

    # Collect per-channel standardized data
    channel_data_list = []
    for channel_id in ordered_channel_ids:
        cal_key = file_channels.get(channel_id)
        if cal_key is None:
            raise ValueError(
                f"Channel '{channel_id}' not found in mapping for '{filename}'"
            )
        cal_data = calibration_dict.get(cal_key)
        if cal_data is None:
            raise ValueError(
                f"Calibration key '{cal_key}' not found in calibration_dict"
            )
        channel_data_list.append(cal_data)

    def _unwrap(value):
        """Unwrap single-element list/tuple to scalar."""
        if isinstance(value, (list, tuple)) and len(value) == 1:
            return value[0]
        return value

    def _collect(std_key):
        """Collect a per-channel field into a list, unwrapping arrays."""
        return [_unwrap(cd.get(std_key)) for cd in channel_data_list]

    def _scalar(std_key):
        """Get a scalar field from the first channel."""
        return _unwrap(channel_data_list[0].get(std_key)) if channel_data_list else None

    # Reverse mapping from standardized names to comparison format names.
    # See convert_params_to_standardized_names for the forward direction.
    cal_params = {
        "gain_correction": _collect("gain_correction"),
        "sa_correction": _collect("sa_correction"),
        "equivalent_beam_angle": _collect("equivalent_beam_angle"),
        "beamwidth_athwartship": _collect("beamwidth_transmit_major"),
        "beamwidth_alongship": _collect("beamwidth_transmit_minor"),
        "angle_offset_athwartship": _collect("echoangle_major"),
        "angle_offset_alongship": _collect("echoangle_minor"),
        "angle_sensitivity_athwartship": _collect("echoangle_major_sensitivity"),
        "angle_sensitivity_alongship": _collect("echoangle_minor_sensitivity"),
    }

    env_params = {
        "sound_speed": _scalar("sound_speed_indicative"),
        "sound_absorption": _collect("absorption_indicative"),
    }

    other_params = {
        "channel": ordered_channel_ids,
        "frequency_nominal": _collect("frequency"),
        "transmit_duration_nominal": _collect("transmit_duration_nominal"),
        "transmit_power": _collect("transmit_power"),
        "transmit_bandwidth": _collect("transmit_bandwidth"),
        "sample_interval": _collect("sample_interval"),
        "source_filenames_across_channels": (
            channel_data_list[0].get("source_filenames") if channel_data_list else None
        ),
        "source_file_type": (
            channel_data_list[0].get("source_file_type") if channel_data_list else None
        ),
    }

    return {
        "cal_params": cal_params,
        "env_params": env_params,
        "other_params": other_params,
    }


def load_standardized_calibration_parameters(
    output_base,
    filename=None,
    echodata=None,
    single_cal_subdir="single_channel_calibration_files",
    mapping_subdir="mapping_files",
    mapping_filename="channel_to_calibration_mapping.yaml",
):
    """Load standardized calibration files and return comparison-format parameters.

    Reads the mapping YAML and single-channel calibration ``.yml`` files from
    the pipeline output directory, reconstructs ``calibration_dict`` and
    ``mapping_dict``, and converts them to the ``(cal_params, env_params,
    other_params)`` structure used by
    :func:`comparison.run_full_calibration_comparison`.

    This is a convenience wrapper around
    :func:`extract_standardized_calibration_parameters` for use in a fresh
    session where ``generate_standardized_cal_mapping`` has not been run.

    Args:
        output_base: Root output directory produced by the pipeline (the same
            path passed as *output_base* to
            :func:`generate_standardized_cal_mapping`).
        filename: Raw filename whose channels to extract.  If *None*, the
            first filename in the mapping is used.
        echodata: Optional EchoData object used to guarantee channel ordering
            alignment with echopype arrays.
        single_cal_subdir: Name of the subdirectory containing single-channel
            ``.yml`` files (default ``"single_channel_calibration_files"``).
        mapping_subdir: Name of the subdirectory containing the mapping YAML
            (default ``"mapping_files"``).
        mapping_filename: Name of the mapping YAML file
            (default ``"channel_to_calibration_mapping.yaml"``).

    Returns:
        dict with keys:
            - ``cal_params``: Calibration parameters.
            - ``env_params``: Environmental parameters.
            - ``other_params``: Other parameters.
            - ``mapping_dict``: The loaded mapping dictionary.
            - ``calibration_dict``: The reconstructed calibration dictionary.
    """
    output_base = Path(output_base)
    cal_files_dir = output_base / single_cal_subdir
    mapping_path = output_base / mapping_subdir / mapping_filename

    if not mapping_path.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_path}")
    if not cal_files_dir.exists():
        raise FileNotFoundError(
            f"Single-channel calibration directory not found: {cal_files_dir}"
        )

    # Load the mapping dictionary
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping_dict = yaml.safe_load(f)

    # Collect all unique calibration keys referenced by the mapping
    cal_keys = set()
    for channels in mapping_dict.values():
        cal_keys.update(channels.values())

    # Load each referenced single-channel calibration file
    calibration_dict = {}
    for cal_key in cal_keys:
        cal_file = cal_files_dir / f"{calibration_key_to_filename(cal_key)}.yml"
        if not cal_file.exists():
            raise FileNotFoundError(
                f"Calibration file not found for key '{cal_key}': {cal_file}"
            )
        with open(cal_file, "r", encoding="utf-8") as f:
            calibration_dict[cal_key] = yaml.safe_load(f)

    # Convert to comparison format
    result = extract_standardized_calibration_parameters(
        calibration_dict, mapping_dict, filename=filename, echodata=echodata,
    )

    result["mapping_dict"] = mapping_dict
    result["calibration_dict"] = calibration_dict
    return result


def print_calibration_values(echodata, params, title="Calibration Values"):
    """Print formatted calibration parameters with appropriate units and formatting.
    
    Prints calibration parameters in echopype's netCDF format, organizing them by
    Environment, Sonar/Beam_group1, and Vendor_specific groups with proper units.
    
    Args:
        echodata: Echopype EchoData object for unit extraction
        params (dict): Consolidated calibration parameters dict with keys:
            - cal_params: Calibration parameters (gain_correction, sa_correction, equivalent_beam_angle, etc.)
            - env_params: Environmental parameters (sound_speed, sound_absorption)
            - other_params: Other parameters (channel, transmit_duration, frequency_nominal, etc.)
        title (str, optional): Title for the printed output. Defaults to "Calibration Values"
    """
    cal_params = params["cal_params"]
    env_params = params["env_params"]
    other_params = params["other_params"]

    # extract data
    sound_speed_num = env_params["sound_speed"]
    absorption_num = env_params["sound_absorption"]
    
    gain_correction_num = cal_params["gain_correction"]
    sa_correction_num = cal_params["sa_correction"]
    equivalent_beam_angle_num = cal_params["equivalent_beam_angle"]
    beamwidth_athwartship_num = cal_params["beamwidth_athwartship"]
    beamwidth_alongship_num = cal_params["beamwidth_alongship"]
    angle_offset_athwartship_num = cal_params["angle_offset_athwartship"]
    angle_offset_alongship_num = cal_params["angle_offset_alongship"]
    angle_sensitivity_athwartship_num = cal_params["angle_sensitivity_athwartship"]
    angle_sensitivity_alongship_num = cal_params["angle_sensitivity_alongship"]


    channels = other_params.get("channel", None)
    frequency_nominal_num = other_params["frequency_nominal"]
    transmit_duration_num = other_params.get("transmit_duration_nominal", None)
    sonar_software_version_num = other_params.get("sonar_software_version", None)
    sample_interval_num = other_params.get("sample_interval", None)
    transmit_power_num = other_params.get("transmit_power", None)
    transmit_bandwidth_num = other_params.get("transmit_bandwidth", None)


    # format numbers and retrieve units
    transmit_bandwidth = [f"{tb:.1f}" for tb in transmit_bandwidth_num]
    transmit_bandwidth_units = echodata["Sonar/Beam_group1"]["transmit_bandwidth"][0][0].units

    sample_interval = [f"{si:.6f}" for si in sample_interval_num]
    sample_interval_units = echodata["Sonar/Beam_group1"]["sample_interval"][0][0].units

    transmit_power = [f"{tp:.1f}" for tp in transmit_power_num]
    transmit_power_units = echodata["Sonar/Beam_group1"]["transmit_power"][0][0].units

    beamwidth_athwartship = [f"{b:.2f}" for b in beamwidth_athwartship_num]
    beamwidth_athwartship_units = "deg" # echodata["Sonar/Beam_group1"]["beamwidth_twoway_athwartship"][0].units

    beamwidth_alongship = [f"{b:.2f}" for b in beamwidth_alongship_num]
    beamwidth_alongship_units = "deg" # echodata["Sonar/Beam_group1"]["beamwidth_twoway_alongship"][0].units

    angle_offset_athwartship = [f"{a:.2f}" for a in angle_offset_athwartship_num]
    angle_offset_athwartship_units = "deg" # echodata["Sonar/Beam_group1"]["angle_offset_athwartship"][0].units

    angle_offset_alongship = [f"{a:.2f}" for a in angle_offset_alongship_num]
    angle_offset_alongship_units = "deg" # echodata["Sonar/Beam_group1"]["angle_offset_alongship"][0].units

    angle_sensitivity_athwartship = [f"{a:.2f}" for a in angle_sensitivity_athwartship_num]
    angle_sensitivity_athwartship_units = "unitless" # echodata["Sonar/Beam_group1"]["angle_sensitivity_athwartship"][0].units

    angle_sensitivity_alongship = [f"{a:.2f}" for a in angle_sensitivity_alongship_num]
    angle_sensitivity_alongship_units = "unitless" # echodata["Sonar/Beam_group1"]["angle_sensitivity_alongship"][0].units

    # Sound Speed
    frequency_nominal = [f"{fn:.0f}" for fn in frequency_nominal_num]
    frequency_nominal_units = echodata["Sonar/Beam_group1"].frequency_nominal[0].units

    # Sound Speed
    sound_speed = f"{sound_speed_num:.1f}"
    sound_speed_units = echodata["Environment"].sound_speed_indicative[0][0].units

    # Absorption
    absorption = [f"{a:.4f}" for a in absorption_num]
    absorption_units = echodata["Environment"].absorption_indicative[0][0].units

    # transmit duration
    if(transmit_duration_num is not None):
        transmit_duration = [f"{td:.6f}" for td in transmit_duration_num]
        transmit_duration_units = echodata["Sonar/Beam_group1"].transmit_duration_nominal.units

    # gain correction

    # NOTE: assuming gain and sa units defined in sonar group also apply to Vendor_specific group
    gain_correction_units = echodata["Sonar/Beam_group1"].gain_correction.units
    gain_correction = [f"{gc:.2f}" for gc in gain_correction_num]

    # sa correction
    # NOTE: hardcoded units for sa correction
    sa_correction_units = "dB"
    sa_correction = [f"{sa:.2f}" for sa in sa_correction_num]

    # equivalent_beam_angle
    equivalent_beam_angle = [f"{eba:.2f}" for eba in equivalent_beam_angle_num]

    # echopype BUG: equivalent beam angle data is in dB re sr, but units just say "sr" for steradians
    # ICES convention is to express in sr directly, which requires conversion
    equivalent_beam_angle_units_BUG = echodata["Sonar/Beam_group1"].equivalent_beam_angle.units
    equivalent_beam_angle_units = "dB re sr"


    # Print out calibration parameters
    def printValues(title, values, units):
        print(f"\t{title}: ")
        print(f"\t\tUnits: {units}")
        print('\t\t', end='')
        print(*values, sep=f' \n\t\t', end=f"  \n")
        print("")

    print(f"{title}\n\n")

    print("Environment:\n")

    print(f"\tsound_speed_indicative: {sound_speed} {sound_speed_units}\n")

    printValues("absorption_indicative", absorption, absorption_units)


    print("\nSonar/:\n")

    print(f"\tsoftware_version: {sonar_software_version_num}\n")


    print("\nSonar/Beam_group1:\n")

    if(channels is not None):
        print("\tchannel:")
        channel_str = '\n\t\t'.join(channels)
        print(f"\t\t{channel_str}\n")

    printValues("frequency", frequency_nominal, frequency_nominal_units)

    if(transmit_duration_num is not None):
        printValues("transmit_duration_nominal", transmit_duration, transmit_duration_units)

    printValues("equivalent_beam_angle", equivalent_beam_angle, equivalent_beam_angle_units)

    printValues("beamwidth_athwartship", beamwidth_athwartship, beamwidth_athwartship_units)

    printValues("beamwidth_alongship", beamwidth_alongship, beamwidth_alongship_units)

    printValues("angle_offset_athwartship", angle_offset_athwartship, angle_offset_athwartship_units)

    printValues("angle_offset_alongship", angle_offset_alongship, angle_offset_alongship_units)

    printValues("angle_sensitivity_athwartship", angle_sensitivity_athwartship, angle_sensitivity_athwartship_units)

    printValues("angle_sensitivity_alongship", angle_sensitivity_alongship, angle_sensitivity_alongship_units)

    printValues("sample_interval", sample_interval, sample_interval_units)

    printValues("transmit_power", transmit_power, transmit_power_units)

    printValues("transmit_bandwidth", transmit_bandwidth, transmit_bandwidth_units)

    print("\nVendor_specific:\n")

    printValues("gain_correction", gain_correction, gain_correction_units)

    printValues("sa_correction", sa_correction, sa_correction_units)



def generate_standardized_cal_mapping(
    raw_input_folder,
    cal_input_folder,
    output_base,
    global_params,
    short_filenames=True,
    keep_unused=True,
    conflict_resolution="error",
    verbose=True,
):
    """Run the full calibration pipeline: raw config extraction, calibration
    standardization, channel-to-calibration mapping, and verification.

    Steps performed:
      1. Read raw file configurations and save to YAML.
      2. Parse manufacturer calibration files (EK60/EK80), validate, and save
         each channel as an individual single-channel .yml file.
      3. Load single-channel files, match raw channels to calibration data,
         handle unused files, resolve conflicts, and save mapping files.
      4. Verify that all required calibration parameters are present and that
         every remaining single-channel file is referenced by the mapping.

    Args:
        raw_input_folder: Path to folder containing .raw files.
        cal_input_folder: Path to folder containing manufacturer calibration
            files (.cal for EK60 or .xml for EK80).
        output_base: Path to the root output directory.  Subdirectories for
            raw configs, single-channel files, mapping files, logs, and
            (optionally) unused calibration files will be created beneath it.
        global_params: Dict of global parameters applied to every single-channel
            file (e.g. ``{"cruise_id": "...", "record_author": "..."}``).
        short_filenames: If True, use compact filenames for single-channel
            calibration files and mapping keys (default True).
        keep_unused: If True, unused/rejected calibration files are moved to
            an ``unused_calibration_files`` subfolder instead of being deleted
            (default True).
        conflict_resolution: Strategy when a raw channel matches multiple
            calibration files.  ``"interactive"`` prompts the user to choose;
            ``"error"`` raises a ValueError listing the conflicts (default).
        verbose: If True, print progress information (default True).

    Returns:
        dict with keys:
            - mapping_dict: {filename: {channel_id: cal_key, ...}, ...}
            - calibration_dict: {cal_key: {param: value, ...}, ...}
            - result: The MappingResult object from build_mapping.
            - missing_params: Dict of calibration keys with missing required
              parameters (empty dict means all present).
            - unused_files: List of Path objects for calibration files not
              referenced by the mapping (empty list means all used).
    """
    raw_input_folder = Path(raw_input_folder)
    cal_input_folder = Path(cal_input_folder)
    output_base = Path(output_base)

    # Create output subdirectories
    raw_configs_output = output_base / "raw_file_configs"
    single_cal_output = output_base / "single_channel_calibration_files"
    mapping_output = output_base / "mapping_files"
    unused_cal_output = output_base / "unused_calibration_files"
    logs_output = output_base / "logs"

    for folder in [raw_configs_output, single_cal_output, mapping_output, logs_output]:
        folder.mkdir(parents=True, exist_ok=True)

    if keep_unused:
        unused_cal_output.mkdir(parents=True, exist_ok=True)

    raw_configs_path = raw_configs_output / "raw_file_configs.yaml"

    # If single-channel calibration files already exist, skip Steps 1-2.
    # This allows the "error" conflict-resolution workflow: after a conflict
    # is raised, the user deletes the unwanted file(s) and re-runs the cell
    # without Steps 1-2 regenerating them.
    existing_cal_files = list(single_cal_output.glob("*.yml"))
    if existing_cal_files:
        if verbose:
            print(f"Found {len(existing_cal_files)} existing single-channel calibration "
                  f"file(s) in {single_cal_output} — skipping Steps 1-2.")
    else:
        # ── STEP 1: Read raw file configurations ─────────────────────────
        file_configs, frequencies_set = process_raw_folder(raw_input_folder, verbose=verbose)
        save_yaml(file_configs, raw_configs_path)
        if verbose:
            print(f"\nSaved raw file configurations to: {raw_configs_path}")

        # ── STEP 2: Parse manufacturer calibration files ─────────────────
        cal_params, env_params, other_params, cal_file_type = \
            manufacturer_file_parsers.extract_and_convert_calibration_params(
                cal_input_folder,
                nc_frequencies=frequencies_set,
                output_logs_folder=logs_output,
            )

        if verbose:
            print("\n" + "=" * 80)
            print(f"Parsed {cal_file_type} calibration parameters summary:")
            print("=" * 80)
            print(f"Channels: {other_params.get('channel')}")
            print(f"Frequencies: {other_params.get('frequency_nominal')}")
            print(f"Gain corrections: {cal_params.get('gain_correction')}")
            print(f"Sa corrections: {cal_params.get('sa_correction')}")
            print(f"Equivalent beam angles: {cal_params.get('equivalent_beam_angle')}")

        # Save as single-channel files
        saved_count, _, standardized_dict = standardized_file_lib.save_single_channel_files_from_params(
            cal_params,
            env_params,
            other_params,
            global_params,
            output_dir=single_cal_output,
            short_filenames=short_filenames,
        )

        if verbose:
            print(f"\nSaved {saved_count} single-channel calibration file(s) to: {single_cal_output}")
            print("\n" + "=" * 80)
            print("Single-channel calibration files:")
            print("=" * 80)
            for f in sorted(single_cal_output.glob("*.yml")):
                size_kb = f.stat().st_size / 1024
                print(f"  {f.name} ({size_kb:.1f} KB)")

    # ── STEP 3: Load configs, build mapping, save ────────────────────────
    raw_file_configs = load_raw_configs(raw_configs_path)

    if verbose:
        print(f"\nLoaded {len(raw_file_configs)} raw file configurations")
        print(f"Raw files: {[f['filename'] for f in raw_file_configs]}")

    calibration_data = load_calibration_data_from_single_files(single_cal_output)

    if verbose:
        print(f"Loaded {len(calibration_data['channels'])} calibration channel(s) "
              f"from {single_cal_output}")

    result = build_mapping(raw_file_configs, calibration_data, verbose=verbose)
    result.print_summary()

    # Handle unused calibration files
    handle_unused_calibration_files(
        result, calibration_data, single_cal_output,
        keep_unused=keep_unused,
        unused_dir=unused_cal_output,
    )

    # Resolve conflicts
    if conflict_resolution == "interactive":
        resolve_conflicts_interactive(
            result, single_cal_output,
            keep_unused=keep_unused,
            unused_dir=unused_cal_output,
        )
    elif conflict_resolution == "error":
        check_for_conflicts(result, cal_files_dir=single_cal_output)
    else:
        raise ValueError(
            f"Unknown conflict_resolution mode: {conflict_resolution!r}. "
            f"Use 'interactive' or 'error'."
        )

    mapping_dict = result.mapping_dict
    calibration_dict = result.calibration_dict

    # Preview and save mapping files
    print_mapping_preview(result)

    mapping_path, calibration_path = save_mapping_files(
        result, mapping_output, short_filenames=short_filenames,
    )

    if verbose:
        print(f"\nSaved mapping dictionary to: {mapping_path}")
        print(f"Saved calibration dictionary to: {calibration_path}")
        print(f"\nNote: Single-channel calibration files already exist in: {single_cal_output}")

    if short_filenames:
        mapping_dict, calibration_dict, short_map = remap_to_short_keys(
            mapping_dict, calibration_dict,
        )
        print_short_key_summary(short_map, result.calibration_dict)

    # ── Verification ─────────────────────────────────────────────────────
    missing_params = check_required_calibration_params(calibration_dict)
    unused_files = verify_calibration_file_usage(calibration_dict, single_cal_output)

    return {
        "mapping_dict": mapping_dict,
        "calibration_dict": calibration_dict,
        "result": result,
        "missing_params": missing_params,
        "unused_files": unused_files,
    }


