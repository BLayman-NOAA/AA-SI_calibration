"""Calibration extraction and pipeline orchestration.

Provides functions for extracting calibration parameters from echopype EchoData objects, 
and converting between standardized and comparison formats
"""

import echopype as ep
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import json
import os
import re

from aa_si_calibration.utils import CalibrationFlags

from aa_si_calibration import _artifacts
from aa_si_calibration import _console
from aa_si_calibration import _storage
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
                    print(f"WARNING: \nParameter '{change_info['parameter']}' changed on {change_info['channel']} "
                          f"at ping {change_info['ping_index']}: "
                          f"{change_info['value_before']} -> {change_info['value_after']}")


def _safe_extract(echodata, group, field, flags, call_values=True):
    """Extract a parameter from echodata, returning None and logging on failure."""
    try:
        data = echodata[group][field]
        return data.values if call_values else data
    except (KeyError, AttributeError):
        flags["missing_parameters"].append(f"{group}/{field}")
        return None


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
    flags = CalibrationFlags(output_logs_folder)
    if "data_irregularities" not in flags or not isinstance(flags["data_irregularities"], dict):
        flags["data_irregularities"] = {"across_frequencies": [], "across_pings": []}
    flags["data_irregularities"].setdefault("across_frequencies", [])
    flags["data_irregularities"].setdefault("across_pings", [])

    sound_speed_num = _safe_extract(echodata, "Environment", "sound_speed_indicative", flags)
    absorption_num = _safe_extract(echodata, "Environment", "absorption_indicative", flags)
    transmit_duration_num = _safe_extract(echodata, "Sonar/Beam_group1", "transmit_duration_nominal", flags)

    try:
        pulse_length_table = echodata["Vendor_specific"].pulse_length.values
        pulse_length_indicies = get_pulse_length_indicies(transmit_duration_num[:,0], pulse_length_table)
    except (KeyError, AttributeError):
        flags["missing_parameters"].append("Vendor_specific/pulse_length")
        pulse_length_table = None
        pulse_length_indicies = None

    try:
        gain_correction_table = echodata["Vendor_specific"].gain_correction.values
        gain_correction_num = [gain_correction_table[i][pulse_length_indicies[i]] for i in range(len(gain_correction_table))]
    except (KeyError, AttributeError, IndexError):
        flags["missing_parameters"].append("Vendor_specific/gain_correction")
        gain_correction_num = None

    try:
        sa_correction_table = echodata["Vendor_specific"].sa_correction.values
        sa_correction_num = [sa_correction_table[i][pulse_length_indicies[i]] for i in range(len(sa_correction_table))]
    except (KeyError, AttributeError, IndexError):
        flags["missing_parameters"].append("Vendor_specific/sa_correction")
        sa_correction_num = None

    equivalent_beam_angle_num = _safe_extract(echodata, "Sonar/Beam_group1", "equivalent_beam_angle", flags)
    channels = _safe_extract(echodata, "Sonar/Beam_group1", "channel", flags)
    frequency_nominal = _safe_extract(echodata, "Sonar/Beam_group1", "frequency_nominal", flags)
    sonar_software_version = _safe_extract(echodata, "Sonar", "sonar_software_version", flags, call_values=False)
    beamwidth_twoway_athwartship = _safe_extract(echodata, "Sonar/Beam_group1", "beamwidth_twoway_athwartship", flags)
    beamwidth_twoway_alongship = _safe_extract(echodata, "Sonar/Beam_group1", "beamwidth_twoway_alongship", flags)
    angle_offset_athwartship = _safe_extract(echodata, "Sonar/Beam_group1", "angle_offset_athwartship", flags)
    angle_offset_alongship = _safe_extract(echodata, "Sonar/Beam_group1", "angle_offset_alongship", flags)
    angle_sensitivity_athwartship = _safe_extract(echodata, "Sonar/Beam_group1", "angle_sensitivity_athwartship", flags)
    angle_sensitivity_alongship = _safe_extract(echodata, "Sonar/Beam_group1", "angle_sensitivity_alongship", flags)
    sample_interval = _safe_extract(echodata, "Sonar/Beam_group1", "sample_interval", flags)
    transmit_power = _safe_extract(echodata, "Sonar/Beam_group1", "transmit_power", flags)
    transmit_bandwidth = _safe_extract(echodata, "Sonar/Beam_group1", "transmit_bandwidth", flags)

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

    flags.save()

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
    calibration_dict, mapping_dict, filename=None, echodata=None, raw_file_path=None,
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
        raw_file_path: Optional full or relative path to a raw file; its
            basename is used as *filename* when *filename* is not given
            directly. Convenience for callers (e.g. a per-file recipe step)
            that only have the raw file's path, not its bare name as it
            appears in *mapping_dict*.

    Returns:
        dict with keys ``cal_params``, ``env_params``, ``other_params``.
    """
    if filename is None and raw_file_path is not None:
        filename = Path(raw_file_path).name
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
    mapping_filename="channel_mapping.yaml",
):
    """Load standardized calibration files and return comparison-format parameters.

    Reads the mapping YAML and single-channel calibration ``.yaml`` files from
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
            ``.yaml`` files (default ``"single_channel_calibration_files"``).
        mapping_subdir: Name of the subdirectory containing the mapping YAML
            (default ``"mapping_files"``).
        mapping_filename: Name of the mapping YAML file
            (default ``"channel_mapping.yaml"``).

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
        cal_file = cal_files_dir / f"{calibration_key_to_filename(cal_key)}.yaml"
        if not cal_file.exists():
            cal_file = cal_files_dir / f"{calibration_key_to_filename(cal_key)}.yml"
        if not cal_file.exists():
            raise FileNotFoundError(
                f"Calibration file not found for key '{cal_key}' "
                f"(tried .yaml and .yml) in: {cal_files_dir}"
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
    beamwidth_athwartship_units = "deg"

    beamwidth_alongship = [f"{b:.2f}" for b in beamwidth_alongship_num]
    beamwidth_alongship_units = "deg"

    angle_offset_athwartship = [f"{a:.2f}" for a in angle_offset_athwartship_num]
    angle_offset_athwartship_units = "deg"

    angle_offset_alongship = [f"{a:.2f}" for a in angle_offset_alongship_num]
    angle_offset_alongship_units = "deg"

    angle_sensitivity_athwartship = [f"{a:.2f}" for a in angle_sensitivity_athwartship_num]
    angle_sensitivity_athwartship_units = "unitless"

    angle_sensitivity_alongship = [f"{a:.2f}" for a in angle_sensitivity_alongship_num]
    angle_sensitivity_alongship_units = "unitless"

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

    gain_correction_units = echodata["Sonar/Beam_group1"].gain_correction.units
    gain_correction = [f"{gc:.2f}" for gc in gain_correction_num]

    sa_correction_units = "dB"
    sa_correction = [f"{sa:.2f}" for sa in sa_correction_num]

    # equivalent_beam_angle
    equivalent_beam_angle = [f"{eba:.2f}" for eba in equivalent_beam_angle_num]

    # ICES convention is tu use "sr" for units, but the values are stored in dB re 1 sr
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



#: Bumped when the fingerprint's shape or the scan's output format changes, so
#: sidecars written by an older version are treated as stale rather than
#: silently trusted.
_RAW_SCAN_FINGERPRINT_VERSION = 1

#: Sidecar recording which raw files (and which window) the saved
#: raw_file_configs.yaml was scanned from.
_RAW_SCAN_FINGERPRINT_NAME = "raw_file_configs.fingerprint.json"


def _raw_scan_fingerprint(
    raw_input_folder, storage_options, file_time_start, file_time_end,
):
    """Identity of a raw scan's inputs: folder contents plus the time window.

    Folder contents are listed, never read, so this is one directory listing
    locally and one ``ls`` on a bucket. Any file added to or removed from the
    folder changes the result, including files outside the window: the listing
    is deliberately taken before the window is applied, which keeps this cheap
    at the cost of an occasional unnecessary re-scan.
    """
    return {
        "version": _RAW_SCAN_FINGERPRINT_VERSION,
        "raw_files": _storage.folder_fingerprint(
            raw_input_folder, "*.raw", storage_options,
        ),
        "file_time_start": None if file_time_start is None else str(file_time_start),
        "file_time_end": None if file_time_end is None else str(file_time_end),
    }


#: Bumped when the fingerprint's shape or the standardized format changes.
_STANDARDIZATION_FINGERPRINT_VERSION = 1

#: Sidecar recording which manufacturer files the single-channel files were
#: parsed from. Kept beside the single-channel folder rather than inside it, so
#: the ``*.yaml`` globs that read that folder do not have to skip it.
_STANDARDIZATION_FINGERPRINT_NAME = "standardization.fingerprint.json"


def _standardization_fingerprint(cal_input_folder, storage_options, short_filenames):
    """Identity of a standardization's inputs.

    One directory listing locally, one ``ls`` on a bucket; the files are never
    read. ``short_filenames`` participates because it sets the names the
    single-channel files are written under, which are the mapping's keys.
    """
    return {
        "version": _STANDARDIZATION_FINGERPRINT_VERSION,
        "cal_files": sorted(
            _storage.folder_fingerprint(cal_input_folder, "*.cal", storage_options)
            + _storage.folder_fingerprint(cal_input_folder, "*.xml", storage_options)
        ),
        "short_filenames": bool(short_filenames),
    }


def _read_fingerprint_sidecar(path):
    """Return the fingerprint recorded at *path*, or None if unreadable.

    An unreadable sidecar means the work is redone rather than trusting
    outputs of unknown provenance.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_fingerprint_sidecar(path, fingerprint):
    """Record *fingerprint* at *path*.

    Called after the outputs it describes are on disk, so an interrupted run
    leaves no sidecar claiming incomplete outputs are current.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fingerprint, f, indent=2)


def _calibration_dirs(output_base, *, keep_unused=False):
    """Create and return the calibration output subdirectories.

    ``unused_calibration_files`` is created only when *keep_unused*; the rest
    always are. Idempotent, so every step may call it.
    """
    output_base = Path(output_base)
    dirs = {
        "raw_configs": output_base / "raw_file_configs",
        "single_cal": output_base / "single_channel_calibration_files",
        "mapping": output_base / "mapping_files",
        "unused_cal": output_base / "unused_calibration_files",
        "logs": output_base / "logs",
    }
    for key in ("raw_configs", "single_cal", "mapping", "logs"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    if keep_unused:
        dirs["unused_cal"].mkdir(parents=True, exist_ok=True)
    return dirs


def _resolve_global_params(cruise_id, record_author, global_params, caller):
    """Reconcile the explicit metadata arguments with the legacy dict form.

    Returns:
        dict with ``cruise_id`` and ``record_author``.

    Raises:
        ValueError: If the two forms disagree, or either value is missing.
        TypeError: If *global_params* is not a dict.
    """
    if global_params is not None and not isinstance(global_params, dict):
        raise TypeError("global_params must be a dict when provided")

    legacy_params = dict(global_params or {})
    resolved_cruise_id = cruise_id if cruise_id is not None else legacy_params.get("cruise_id")
    resolved_record_author = (
        record_author if record_author is not None else legacy_params.get("record_author")
    )

    if cruise_id is not None and "cruise_id" in legacy_params and legacy_params["cruise_id"] != cruise_id:
        raise ValueError(
            "cruise_id does not match global_params['cruise_id']: "
            f"{cruise_id!r} != {legacy_params['cruise_id']!r}"
        )

    if (
        record_author is not None
        and "record_author" in legacy_params
        and legacy_params["record_author"] != record_author
    ):
        raise ValueError(
            "record_author does not match global_params['record_author']: "
            f"{record_author!r} != {legacy_params['record_author']!r}"
        )

    missing_global_keys = [
        key
        for key, value in {
            "cruise_id": resolved_cruise_id,
            "record_author": resolved_record_author,
        }.items()
        if value is None
    ]
    if missing_global_keys:
        missing_keys_str = ", ".join(missing_global_keys)
        raise ValueError(
            f"{caller} requires values for "
            f"{missing_keys_str}. Provide them explicitly or via global_params."
        )

    return {
        "cruise_id": resolved_cruise_id,
        "record_author": resolved_record_author,
    }


def _frequencies_from_configs(file_configs):
    """Unique channel frequencies (Hz) across saved raw file configurations.

    Recovers the second half of :func:`process_raw_folder`'s return value from
    the configs on disk, so Step 2 can run against a reused Step 1.
    """
    return {
        channel["frequency"]
        for config in file_configs
        for channel in config.get("channels", [])
        if "frequency" in channel
    }


def _process_raw_folder_remote(
    raw_url,
    storage_options=None,
    verbose=True,
    verify_start_time=False,
    file_time_start=None,
    file_time_end=None,
):
    """Scan a remote (``gs://``) folder of .raw files one file at a time.

    Mirrors :func:`process_raw_folder`'s contract, but downloads each file to a
    private local scratch dir, scans it, and deletes the local copy before the
    next file is fetched, so local disk only ever holds one raw file. The
    filename-time filter is applied to the listing, so excluded files are never
    downloaded (the one file straddling the window's start has its trailing
    headers range-read to place it). Bucket objects are never modified or
    removed.

    Returns:
        tuple: ``(file_configs, frequencies_set)``, sorted identically to
        :func:`process_raw_folder`.
    """
    from .raw_reader_api import _config_sort_key, process_raw_file

    raw_urls = _storage.glob_url(raw_url, "*.raw", storage_options)
    if not raw_urls:
        raise FileNotFoundError(f"No .raw files found in: {raw_url}")

    if file_time_start is not None or file_time_end is not None:
        before = len(raw_urls)
        raw_urls = _storage.filter_paths_by_file_time(
            raw_urls,
            file_time_start,
            file_time_end,
            storage_options=storage_options,
            verbose=verbose,
        )
        if verbose:
            print(
                f"  Filename-time filter: {before} -> {len(raw_urls)} raw file(s) "
                f"({file_time_start} to {file_time_end})"
            )
        if not raw_urls:
            raise FileNotFoundError(
                f"No .raw files in {raw_url} within the filename-time window "
                f"({file_time_start} to {file_time_end})"
            )

    if verbose:
        print(f"Found {len(raw_urls)} raw files in {raw_url}")
        for url in raw_urls:
            print(f"  - {_storage.basename(url)}")

    file_configs = []
    frequencies_set = set()

    for url in raw_urls:
        with _storage.localized_file(url, storage_options=storage_options) as local_raw:
            file_config = process_raw_file(
                local_raw, verbose=verbose, verify_start_time=verify_start_time
            )
        # The local copy is gone by here, before the next file downloads.
        if file_config is None:
            continue

        file_configs.append(file_config)
        for ch in file_config.get("channels", []):
            if "frequency" in ch:
                frequencies_set.add(ch["frequency"])

    file_configs.sort(key=_config_sort_key)

    if verbose:
        print("\n" + "=" * 80)
        print(f"SUMMARY: Processed {len(file_configs)} files (sorted by metadata_start_time)")
        print(f"Unique frequencies found: {sorted(frequencies_set)} Hz")
        print("=" * 80)

    return file_configs, frequencies_set


#: Fields :func:`_read_config_from_prefix` cannot measure from a prefix, because
#: each is accumulated over every datagram in the file.
_WHOLE_FILE_FIELDS = ("raw3_count", "gps_data")


def _channels_are_complete(config):
    """True when every channel carries values from a Parameter datagram.

    A prefix that stops before a channel's first Parameter datagram still
    yields that channel, built from the Configuration datagram alone: no pulse
    length, no transmit power, and a pulse_form defaulted to CW that would
    misreport an FM channel. Such a configuration is not usable, and the caller
    reads the whole file instead.
    """
    channels = config.get("channels")
    if not channels:
        return False
    return all(
        channel.get("transmit_duration_nominal") is not None
        and channel.get("transmit_power") is not None
        for channel in channels
    )


#: First prefix tried. A CW file settles well inside this; an FM file's
#: Parameter datagrams sit behind much larger RAW3 payloads and generally do
#: not, which is what the ladder above it is for.
_PREFIX_LADDER_START = 8 * 2**20


def _prefix_ladder(max_bytes, start=None):
    """Yield doubling prefix sizes from *start* up to *max_bytes*, inclusive.

    Doubling rather than jumping straight to *max_bytes* keeps the common case
    cheap: a file whose configuration settles early pays one small read, and
    only the files that need more climb. Because the local prefix grows in
    place, climbing transfers each byte once.
    """
    n_bytes = min(start or _PREFIX_LADDER_START, max_bytes)
    while True:
        yield n_bytes
        if n_bytes >= max_bytes:
            return
        n_bytes = min(n_bytes * 2, max_bytes)


def _read_config_from_prefix(url, max_scan_bytes, storage_options, verbose=True):
    """Read an EK80 file's channel configuration from its leading bytes.

    Climbs :func:`_prefix_ladder`, extending the local prefix until the channel
    configuration is complete. Returns None when it never is, which sends the
    caller back to the whole-file read: a non-EK80 file, a file whose
    configuration is not settled within *max_scan_bytes*, or one that does not
    scan at all.

    ``last_ping_time`` is recovered from the file's tail, which costs a few
    hundred bytes. The fields in :data:`_WHOLE_FILE_FIELDS` are cleared rather
    than reported from the prefix, where they would count only the datagrams
    that happened to fit.
    """
    from datetime import timezone

    from .raw_file_times import last_ping_time
    from .raw_reader_api import detect_instrument_type, process_raw_file

    config = None
    with _storage.localized_file_head(url, storage_options=storage_options) as fetch:
        for n_bytes in _prefix_ladder(max_scan_bytes):
            prefix = fetch(n_bytes)
            if detect_instrument_type(prefix) != "EK80":
                return None
            candidate = process_raw_file(
                prefix, verbose=verbose, verify_start_time=False
            )
            if candidate is not None and _channels_are_complete(candidate):
                config = candidate
                break
            # A short read means the object is exhausted, so no larger prefix
            # exists and the whole-file path is the only thing left to try.
            if prefix.stat().st_size < n_bytes:
                break

    if config is None:
        return None

    for field in _WHOLE_FILE_FIELDS:
        config[field] = None
    end = last_ping_time(url, storage_options=storage_options)
    config["last_ping_time"] = (
        end.replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds")
        if end is not None
        else None
    )
    return config


def read_raw_file_config(
    raw_file_path, verify_start_time=False, verbose=True, max_scan_bytes=None
):
    """Read one raw file's channel configuration.

    The single-file half of :func:`process_raw_folder`. A remote file is
    downloaded to local scratch, scanned, and the local copy deleted before
    this returns. Bucket objects are never modified.

    Args:
        raw_file_path: Path to a .raw file. May be a remote fsspec URL, which
            requires ``pip install aa-si-calibration[gcs]``.
        verify_start_time: If True, EK80 files are additionally read with the
            full SimradFileReader to verify metadata_start_time (slower).
        verbose: If True, print progress information.
        max_scan_bytes: When set, read only this many leading bytes of a remote
            EK80 file instead of transferring it whole. The channel
            configuration sits within the first few MiB, so this is the setting
            for scanning a survey whose raw files are large or far away. Falls
            back to the whole file whenever the prefix does not settle the
            configuration, and reports ``raw3_count`` and ``gps_data`` as None
            because a prefix cannot measure them. Ignored for local files and
            when verify_start_time is set.

    Returns:
        dict: The file's configuration, or None when it could not be read.
        Callers accumulating these should drop the None entries.
    """
    from .raw_reader_api import _clean_value, _ensure_string_identifiers, process_raw_file

    if not _storage.is_remote(raw_file_path):
        config = process_raw_file(
            Path(raw_file_path), verbose=verbose, verify_start_time=verify_start_time
        )
    else:
        storage_options = _storage.execution_storage_options()
        config = None
        if max_scan_bytes and not verify_start_time:
            config = _read_config_from_prefix(
                str(raw_file_path), max_scan_bytes, storage_options, verbose=verbose
            )
        if config is None:
            with _storage.localized_file(
                str(raw_file_path), storage_options=storage_options
            ) as local_raw:
                config = process_raw_file(
                    local_raw, verbose=verbose, verify_start_time=verify_start_time
                )

    if config is None:
        return None
    # The normalization save_yaml applies before writing, done here so the
    # returned config is JSON-safe: a recipe checkpoints it per file, and a
    # value that is not JSON-safe falls back to pickle.
    return _ensure_string_identifiers(_clean_value(config))


def record_raw_file_configs(file_configs, output_base, verbose=True):
    """Save a set of raw file configurations as the survey's raw config file.

    The fan-in half of the raw scan. Drops the files that could not be read,
    sorts the rest into the order :func:`process_raw_folder` returns, and
    writes ``raw_file_configs/raw_file_configs.yaml`` under *output_base*.

    Args:
        file_configs: Per-file configuration dicts. None entries are dropped.
        output_base: Root directory the calibration artifacts are written under.
        verbose: If True, print progress information.

    Returns:
        dict with keys:
            - raw_file_configs: The sorted configurations that were saved.
            - frequencies: Sorted unique channel frequencies (Hz), which
              standardize_calibration_files uses to order EK60 data.
            - raw_configs_path: Full path of the file that was written.

    Raises:
        ValueError: If no readable configurations were supplied.
    """
    from .raw_reader_api import _config_sort_key

    dirs = _calibration_dirs(output_base)
    raw_configs_path = dirs["raw_configs"] / "raw_file_configs.yaml"

    configs = [config for config in file_configs if config is not None]
    if not configs:
        raise ValueError(
            "No raw file configurations to record: every scanned file was "
            "unreadable, or none were supplied."
        )
    configs.sort(key=_config_sort_key)

    frequencies = sorted(_frequencies_from_configs(configs))

    save_yaml(configs, raw_configs_path)
    _artifacts.record_artifact(raw_configs_path)

    if verbose:
        print("\n" + "=" * 80)
        print(f"SUMMARY: Recorded {len(configs)} raw file configuration(s)")
        print(f"Unique frequencies found: {frequencies} Hz")
        print("=" * 80)
        print(f"Saved raw file configurations to: {raw_configs_path}")

    return {
        "raw_file_configs": configs,
        "frequencies": frequencies,
        "raw_configs_path": str(raw_configs_path),
    }


def standardize_calibration_files(
    cal_input_folder,
    output_base,
    frequencies=None,
    cruise_id=None,
    record_author=None,
    global_params=None,
    short_filenames=True,
    overwrite=False,
    verbose=True,
):
    """Convert manufacturer calibration files to standardized single-channel files.

    Parses the EK60 ``.cal`` or EK80 ``.xml`` files in *cal_input_folder*,
    validates them against the standardized schema, and writes one
    ``.yaml`` per channel into ``single_channel_calibration_files/`` under
    *output_base*.

    The parse is skipped when ``standardization.fingerprint.json`` shows the
    same manufacturer files already produced the files that are there. That
    sidecar answers to the manufacturer folder, so deleting a single-channel
    file does not bring it back, which is what the
    ``conflict_resolution="error"`` workflow relies on. It is written only
    after every channel file lands, so an interrupted parse redoes itself.
    Emptying the folder re-parses, as does *overwrite*.

    Args:
        cal_input_folder: Folder of manufacturer calibration files (.cal for
            EK60, .xml for EK80). May be a remote fsspec URL, which is
            downloaded to local scratch for the duration of the parse.
        output_base: Root directory the calibration artifacts are written under.
        frequencies: Channel frequencies (Hz) ordering EK60 calibration data,
            normally from :func:`record_raw_file_configs`. Recovered from the
            saved raw_file_configs.yaml when omitted; optional for EK80.
        cruise_id: Cruise identifier recorded in every generated file.
        record_author: Name recorded as the author of every generated file.
        global_params: Legacy dict form of *cruise_id* and *record_author*.
        short_filenames: If True, use compact single-channel filenames.
        overwrite: If True, re-parse even when the sidecar says the existing
            files are current.
        verbose: If True, print progress information.

    Returns:
        dict with keys:
            - single_channel_dir: Path to the single-channel output folder.
            - channel_count: Number of single-channel files now in that folder.
            - skipped: True when the existing files were reused.
    """
    cal_input_remote = _storage.is_remote(cal_input_folder)
    if not cal_input_remote:
        cal_input_folder = Path(cal_input_folder)

    resolved_global_params = _resolve_global_params(
        cruise_id, record_author, global_params, "standardize_calibration_files"
    )

    dirs = _calibration_dirs(output_base)
    single_cal_output = dirs["single_cal"]
    logs_output = dirs["logs"]
    fingerprint_path = Path(output_base) / _STANDARDIZATION_FINGERPRINT_NAME

    input_options = _storage.execution_storage_options() if cal_input_remote else None
    fingerprint = _standardization_fingerprint(
        cal_input_folder, input_options, short_filenames
    )

    existing_cal_files = (
        list(single_cal_output.glob("*.yaml")) + list(single_cal_output.glob("*.yml"))
    )
    if (
        not overwrite
        and existing_cal_files
        and _read_fingerprint_sidecar(fingerprint_path) == fingerprint
    ):
        if verbose:
            print(
                f"Found {len(existing_cal_files)} single-channel calibration file(s) "
                f"already standardized from these manufacturer files in "
                f"{single_cal_output}, skipping the parse."
            )
        _artifacts.record_artifact(single_cal_output)
        return {
            "single_channel_dir": str(single_cal_output),
            "channel_count": len(existing_cal_files),
            "skipped": True,
        }

    if frequencies is None:
        frequencies = _frequencies_from_configs(
            load_raw_configs(dirs["raw_configs"] / "raw_file_configs.yaml")
        )

    # The parsers are strictly local-filesystem code, so a remote cal folder is
    # materialized locally for the duration of the parse (these files are small).
    if cal_input_remote:
        with _storage.localized_folder(
            str(cal_input_folder),
            ("*.cal", "*.xml"),
            input_options,
        ) as local_cal_folder:
            cal_params, env_params, other_params, cal_file_type = \
                manufacturer_file_parsers.extract_and_convert_calibration_params(
                    local_cal_folder,
                    nc_frequencies=frequencies,
                    output_logs_folder=logs_output,
                )
    else:
        cal_params, env_params, other_params, cal_file_type = \
            manufacturer_file_parsers.extract_and_convert_calibration_params(
                cal_input_folder,
                nc_frequencies=frequencies,
                output_logs_folder=logs_output,
            )

    if verbose:
        print(f"\nParsed {cal_file_type} calibration parameters:")
        print(f"Channels: {other_params.get('channel')}")
        print(f"Frequencies: {other_params.get('frequency_nominal')}")
        print(f"Gain corrections: {cal_params.get('gain_correction')}")
        print(f"Sa corrections: {cal_params.get('sa_correction')}")
        print(f"Equivalent beam angles: {cal_params.get('equivalent_beam_angle')}")

    saved_count, _, _standardized_dict = standardized_file_lib.save_single_channel_files_from_params(
        cal_params,
        env_params,
        other_params,
        resolved_global_params,
        output_dir=single_cal_output,
        short_filenames=short_filenames,
    )

    # Written after the channel files, so an interrupted parse leaves no
    # sidecar claiming the partial set is current.
    _write_fingerprint_sidecar(fingerprint_path, fingerprint)
    _artifacts.record_artifact(single_cal_output)

    if verbose:
        print(f"\nSaved {saved_count} single-channel calibration file(s) to: {single_cal_output}")
        print("\nSingle-channel calibration files:")
        for f in sorted(single_cal_output.glob("*.yaml")):
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name} ({size_kb:.1f} KB)")

    return {
        "single_channel_dir": str(single_cal_output),
        "channel_count": saved_count,
        "skipped": False,
    }


def build_calibration_mapping(
    output_base,
    single_channel_dir=None,
    raw_configs_path=None,
    raw_file_configs=None,
    conflict_resolution="error",
    keep_unused=True,
    short_filenames=True,
    verbose=True,
):
    """Match each raw channel to its calibration data and save the mapping.

    Loads the raw file configurations and the standardized single-channel
    files, runs the matching algorithm, moves aside any calibration file no raw
    channel matched, resolves conflicts, writes the mapping files, and verifies
    the result.

    Reads the single-channel files from disk rather than taking them as data,
    because the mapping keys are those files' names and because this step
    rewrites that folder.

    Args:
        output_base: Root directory the calibration artifacts are written under.
        single_channel_dir: Folder of standardized single-channel files.
            Defaults to ``single_channel_calibration_files/`` under
            *output_base*.
        raw_configs_path: Path of the saved raw_file_configs.yaml. Defaults to
            ``raw_file_configs/raw_file_configs.yaml`` under *output_base*.
            Only consulted when *raw_file_configs* is not supplied.
        raw_file_configs: The raw file configurations to map. When omitted they
            are read from the saved raw_file_configs.yaml.
        conflict_resolution: ``"error"`` raises a ValueError listing the
            conflicts (default); ``"interactive"`` prompts for a choice, which
            needs a terminal.
        keep_unused: If True, unused/rejected calibration files are moved to an
            ``unused_calibration_files`` subfolder instead of being deleted.
        short_filenames: If True, remap the returned dictionaries to compact
            keys.
        verbose: If True, print progress information.

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
    if conflict_resolution not in ("error", "interactive"):
        raise ValueError(
            f"Unknown conflict_resolution mode: {conflict_resolution!r}. "
            f"Use 'interactive' or 'error'."
        )
    if conflict_resolution == "interactive":
        # Checked before anything is moved, so a run that could not answer the
        # prompt fails before relocating any file.
        _console.require_console()

    dirs = _calibration_dirs(output_base, keep_unused=keep_unused)
    single_cal_output = (
        dirs["single_cal"] if single_channel_dir is None else Path(single_channel_dir)
    )
    mapping_output = dirs["mapping"]
    unused_cal_output = dirs["unused_cal"]

    if raw_file_configs is None:
        raw_file_configs = load_raw_configs(
            dirs["raw_configs"] / "raw_file_configs.yaml"
            if raw_configs_path is None
            else Path(raw_configs_path)
        )

    if verbose:
        print(f"\nLoaded {len(raw_file_configs)} raw file configurations")
        print(f"Raw files: {[f['filename'] for f in raw_file_configs]}")

    calibration_data = load_calibration_data_from_single_files(single_cal_output)

    if verbose:
        print(f"Loaded {len(calibration_data['channels'])} calibration channel(s) "
              f"from {single_cal_output}")

    result = build_mapping(raw_file_configs, calibration_data, verbose=verbose)
    result.print_summary()

    # Runs before conflict resolution, so an "error" run has tidied the folder
    # by the time it raises.
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
    else:
        check_for_conflicts(result, cal_files_dir=single_cal_output)

    mapping_dict = result.mapping_dict
    calibration_dict = result.calibration_dict

    # Preview and save mapping files
    print_mapping_preview(result)

    mapping_path, calibration_path = save_mapping_files(
        result, mapping_output, short_filenames=short_filenames,
    )
    _artifacts.record_artifact(mapping_path)
    _artifacts.record_artifact(calibration_path)

    if verbose:
        print(f"\nSaved mapping dictionary to: {mapping_path}")
        print(f"Saved calibration dictionary to: {calibration_path}")
        print(f"\nNote: Single-channel calibration files already exist in: {single_cal_output}")

    if short_filenames:
        mapping_dict, calibration_dict, short_map = remap_to_short_keys(
            mapping_dict, calibration_dict,
        )
        print_short_key_summary(short_map, result.calibration_dict)

    # Verification
    missing_params = check_required_calibration_params(calibration_dict)
    unused_files = verify_calibration_file_usage(calibration_dict, single_cal_output)

    return {
        "mapping_dict": mapping_dict,
        "calibration_dict": calibration_dict,
        "result": result,
        "missing_params": missing_params,
        "unused_files": unused_files,
        # Paths are not JSON-safe, so the recipe output port maps to these.
        "unused_file_names": [Path(f).name for f in unused_files],
    }


def _scan_and_record_raw_configs(
    raw_input_folder,
    output_base,
    verbose=True,
    verify_start_time=False,
    file_time_start=None,
    file_time_end=None,
):
    """Scan a whole folder of raw files and save their configurations.

    The folder at a time scan behind :func:`generate_standardized_cal_mapping`,
    reused only when ``raw_file_configs.fingerprint.json`` shows the saved
    configurations came from the same files and window. Recipes fan the scan
    out per file instead, with :func:`read_raw_file_config` mapped over the raw
    file list and :func:`record_raw_file_configs` collecting the results.

    Returns:
        tuple: ``(file_configs, frequencies_set)``.
    """
    raw_input_remote = _storage.is_remote(raw_input_folder)
    if not raw_input_remote:
        raw_input_folder = Path(raw_input_folder)

    dirs = _calibration_dirs(output_base)
    raw_configs_path = dirs["raw_configs"] / "raw_file_configs.yaml"
    raw_scan_fingerprint_path = dirs["raw_configs"] / _RAW_SCAN_FINGERPRINT_NAME

    input_options = _storage.execution_storage_options() if raw_input_remote else None
    scan_fingerprint = _raw_scan_fingerprint(
        raw_input_folder, input_options, file_time_start, file_time_end,
    )
    reuse_raw_configs = (
        raw_configs_path.exists()
        and _read_fingerprint_sidecar(raw_scan_fingerprint_path) == scan_fingerprint
    )

    if reuse_raw_configs:
        if verbose:
            print(f"Raw file configurations match the requested raw files and "
                  f"window, skipping Step 1: {raw_configs_path}")
        _artifacts.record_artifact(raw_configs_path)
        return load_raw_configs(raw_configs_path), None

    if raw_input_remote:
        file_configs, frequencies_set = _process_raw_folder_remote(
            str(raw_input_folder),
            storage_options=input_options,
            verbose=verbose,
            verify_start_time=verify_start_time,
            file_time_start=file_time_start,
            file_time_end=file_time_end,
        )
    else:
        # Filter the glob result up front so excluded files are never read
        # in full (the boundary file's headers are read to place it).
        local_raw_files = sorted(raw_input_folder.glob("*.raw"))
        if file_time_start is not None or file_time_end is not None:
            before = len(local_raw_files)
            local_raw_files = _storage.filter_paths_by_file_time(
                local_raw_files,
                file_time_start,
                file_time_end,
                verbose=verbose,
            )
            if verbose:
                print(
                    f"  Filename-time filter: {before} -> "
                    f"{len(local_raw_files)} raw file(s) "
                    f"({file_time_start} to {file_time_end})"
                )
            if not local_raw_files:
                raise FileNotFoundError(
                    f"No .raw files in {raw_input_folder} within the "
                    f"filename-time window ({file_time_start} to {file_time_end})"
                )
            raw_files_arg = local_raw_files
        else:
            # Let process_raw_folder glob as before (byte-identical path).
            raw_files_arg = None

        file_configs, frequencies_set = process_raw_folder(
            raw_input_folder,
            verbose=verbose,
            verify_start_time=verify_start_time,
            raw_files=raw_files_arg,
        )

    save_yaml(file_configs, raw_configs_path)
    # Written after the configs so a crash mid-scan leaves no fingerprint
    # claiming the incomplete file is current.
    _write_fingerprint_sidecar(raw_scan_fingerprint_path, scan_fingerprint)
    _artifacts.record_artifact(raw_configs_path)
    if verbose:
        print(f"\nSaved raw file configurations to: {raw_configs_path}")

    return file_configs, frequencies_set


def generate_standardized_cal_mapping(
    raw_input_folder,
    cal_input_folder,
    output_base,
    global_params=None,
    cruise_id=None,
    record_author=None,
    short_filenames=True,
    keep_unused=True,
    conflict_resolution="error",
    verbose=True,
    verify_start_time=False,
    file_time_start=None,
    file_time_end=None,
):
    """Run the full calibration pipeline: raw config extraction, calibration
    standardization, channel-to-calibration mapping, and verification.

    A thin sequence over the public steps, which a recipe calls individually so
    each is cached on its own: :func:`read_raw_file_config` and
    :func:`record_raw_file_configs`, :func:`standardize_calibration_files`,
    then :func:`build_calibration_mapping`.

    Steps performed:
      1. Read raw file configurations and save to YAML.
      2. Parse manufacturer calibration files (EK60/EK80), validate, and save
         each channel as an individual single-channel .yaml file.
      3. Load single-channel files, match raw channels to calibration data,
         handle unused files, resolve conflicts, and save mapping files.
      4. Verify that all required calibration parameters are present and that
         every remaining single-channel file is referenced by the mapping.

    Steps 1 and 2 are skipped independently when their outputs are already
    current under *output_base*, so re-running is cheap:

      * Step 1 is reused only when the saved ``raw_file_configs.yaml`` was
        scanned from the same raw files and the same time window being asked
        for now, recorded in a ``raw_file_configs.fingerprint.json`` sidecar.
        Point *raw_input_folder* somewhere else, or move the window, and the
        scan re-runs. This is the expensive step on a ``gs://`` folder.
      * Step 2 is reused when ``standardization.fingerprint.json`` shows the
        same manufacturer files already produced the single-channel files that
        are there. Deleting one of those files does not bring it back, which is
        what the ``"error"`` conflict workflow relies on. To force a re-parse,
        delete the sidecar.

    Steps 3 and 4 always run, so the mapping files always reflect the current
    raw configs and single-channel files.

    Args:
        raw_input_folder: Path to folder containing .raw files. May be a remote
            fsspec URL (``gs://bucket/survey/raw``), in which case each raw file
            is downloaded to local scratch, scanned, and its local copy deleted
            before the next is fetched. Requires ``pip install
            aa-si-calibration[gcs]``.
        cal_input_folder: Path to folder containing manufacturer calibration
            files (.cal for EK60 or .xml for EK80). May be a remote fsspec URL;
            these files are small, so the folder is downloaded to a local
            scratch directory for the duration of the parse.
        output_base: Path to the root output directory.  Subdirectories for
            raw configs, single-channel files, mapping files, logs, and
            (optionally) unused calibration files will be created beneath it.
        global_params: Optional dict of global parameters applied to every
            single-channel file (e.g. ``{"cruise_id": "...",
            "record_author": "..."}``). Kept for backward compatibility.
        cruise_id: Optional cruise identifier to apply to every generated
            single-channel file. Overrides or validates against
            ``global_params["cruise_id"]`` when provided.
        record_author: Optional record author to apply to every generated
            single-channel file. Overrides or validates against
            ``global_params["record_author"]`` when provided.
        short_filenames: If True, use compact filenames for single-channel
            calibration files and mapping keys (default True).
        keep_unused: If True, unused/rejected calibration files are moved to
            an ``unused_calibration_files`` subfolder instead of being deleted
            (default True).
        conflict_resolution: Strategy when a raw channel matches multiple
            calibration files.  ``"interactive"`` prompts the user to choose;
            ``"error"`` raises a ValueError listing the conflicts (default).
        verbose: If True, print progress information (default True).
        verify_start_time: Forwarded to process_raw_folder. If True, EK80 files
            are additionally read with the full SimradFileReader to verify
            metadata_start_time (slower). Default False uses the fast single
            pass scan.
        file_time_start: Optional inclusive lower bound (ISO string or datetime)
            on each raw file's recording span, restricting which raw files are
            scanned. The span is inferred from the ``D{YYYYMMDD}-T{HHMMSS}``
            name stamps: a file's own stamp is its start and the next file's
            stamp is its end, so a file that starts before this bound but
            records into the window is kept. Should match the window used to
            select files for processing. For a remote folder the filter runs
            before any file is downloaded.
        file_time_end: Optional inclusive upper bound; see *file_time_start*.

    Returns:
        dict with keys:
            - mapping_dict: {filename: {channel_id: cal_key, ...}, ...}
            - calibration_dict: {cal_key: {param: value, ...}, ...}
            - result: The MappingResult object from build_mapping.
            - missing_params: Dict of calibration keys with missing required
              parameters (empty dict means all present).
            - unused_files: List of Path objects for calibration files not
              referenced by the mapping (empty list means all used).
            - unused_file_names: The same files as plain names, which unlike
              Path objects survive a round trip through JSON.
    """
    # The input folders may be URLs and are coerced by the steps that read
    # them; outputs always stay local.
    output_base = Path(output_base)

    # Validated before any I/O, so a metadata mistake does not half-write a
    # calibration folder.
    global_params = _resolve_global_params(
        cruise_id, record_author, global_params, "generate_standardized_cal_mapping"
    )

    _calibration_dirs(output_base, keep_unused=keep_unused)

    # Step 1: read raw file configurations.
    _file_configs, frequencies_set = _scan_and_record_raw_configs(
        raw_input_folder,
        output_base,
        verbose=verbose,
        verify_start_time=verify_start_time,
        file_time_start=file_time_start,
        file_time_end=file_time_end,
    )

    # Step 2: convert manufacturer files to standardized single-channel files.
    standardize_calibration_files(
        cal_input_folder,
        output_base,
        frequencies=frequencies_set,
        global_params=global_params,
        short_filenames=short_filenames,
        verbose=verbose,
    )

    # Steps 3 and 4: map, resolve conflicts, save, verify.
    return build_calibration_mapping(
        output_base,
        conflict_resolution=conflict_resolution,
        keep_unused=keep_unused,
        short_filenames=short_filenames,
        verbose=verbose,
    )
