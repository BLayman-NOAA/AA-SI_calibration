# imports and variables
import echopype as ep 
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import json
import os
import re





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


def print_calibration_values(echodata, env_params, cal_params, other_params, title="Calibration Values"):
    """Print formatted calibration parameters with appropriate units and formatting.
    
    Prints calibration parameters in echopype's netCDF format, organizing them by
    Environment, Sonar/Beam_group1, and Vendor_specific groups with proper units.
    
    Args:
        echodata: Echopype EchoData object for unit extraction
        env_params (dict): Environmental parameters (sound_speed, sound_absorption)
        cal_params (dict): Calibration parameters (gain_correction, sa_correction, equivalent_beam_angle)
        other_params (dict): Other parameters (channels, transmit_duration, frequency_nominal)
        title (str, optional): Title for the printed output. Defaults to "Calibration Values"
    """

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


def calculate_full_dataset_effect(ds_modified, ds_baseline, parameter_name, output_logs_folder, thresholds=None):
    """Calculate the statistical effect of a calibration parameter across the entire dataset.
    
    Computes statistics on the difference between modified and baseline Sv datasets,
    providing comprehensive analysis of how a calibration parameter affects the data.
    
    Args:
        ds_modified: Sv dataset with modified calibration parameter
        ds_baseline: Baseline Sv dataset for comparison
        parameter_name (str): Name of the parameter being analyzed for display
        output_logs_folder: Path to folder for saving log files
        
    Returns:
        dict: Dictionary with frequency keys containing statistical results:
              - mean: Mean difference in dB
              - median: Median difference in dB
              - max_abs: Maximum absolute difference in dB
              - percentile_95: 95th percentile of absolute differences
              - n_valid: Number of valid data points
    """

    default_thresholds = {
                    "critical_median": 2.0,
                    "large_median": 1.0,
                    "moderate_median": 0.5,
                    "critical_max": 4.0,
                    "large_max": 2.0,
                    "moderate_max": 1.0
                }

    if not thresholds:
        thresholds = default_thresholds
    else:
        for key, default_value in default_thresholds.items():
            thresholds.setdefault(key, default_value)
    
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
            "data_irregularities": [],
            "missing_parameters": []
        }
    
    # Calculate difference across all data
    diff_data = ds_modified['Sv'] - ds_baseline['Sv']
    
    print(f"\n {parameter_name.upper()}")
    print("="*60)
    print("Freq     | Mean Effect | Median Effect | Max Absolute Effect | Absolute 95th %ile | Valid Points")
    print("-" * 78)
    
    results = {}
    for freq_hz, channel in zip(ds_baseline["frequency_nominal"].values, ds_baseline["channel"].values):
        freq_key = f"{freq_hz/1000:.0f}kHz"
        
        # Get all valid differences for this frequency
        freq_diff = diff_data.sel(channel=channel)
        valid_diffs = freq_diff.values[~np.isnan(freq_diff.values)]
        
        if len(valid_diffs) > 0:
            stats = {
                'mean': np.mean(valid_diffs),
                'median': np.median(valid_diffs),
                'max_abs': np.max(np.abs(valid_diffs)),
                'percentile_95': np.percentile(np.abs(valid_diffs), 95),
                'n_valid': len(valid_diffs)
            }
            
            results[freq_key] = stats
            print(f"{freq_key:>7} | {stats['mean']:+12.3f} | {stats['median']:+12.3f} | {stats['max_abs']:+20.3f} | {stats['percentile_95']:+18.3f} | {stats['n_valid']:>11,}")
            
            # Check thresholds and log impacts
            median_abs = stats['median']
            max_abs = stats['max_abs']

            median_json_object = {
                "parameter_name": parameter_name,
                "frequency": int(freq_hz),
                "metric": "median",
                "sv_change": round(stats['median'], 3)
            }

            max_json_object = {
                "parameter_name": parameter_name,
                "frequency": int(freq_hz),
                "metric": "max_abs",
                "sv_change": round(stats['max_abs'], 3)
            }

            # Median difference thresholds
            if median_abs > thresholds["critical_median"]:
                flags["critical_impacts"].append(median_json_object)
            elif median_abs > thresholds["large_median"]:
                flags["large_impacts"].append(median_json_object)
            elif median_abs > thresholds["moderate_median"]:
                flags["moderate_impacts"].append(median_json_object)
            
            # Max absolute difference thresholds
            if max_abs > thresholds["critical_max"]:
                flags["critical_impacts"].append(max_json_object)
            elif max_abs > thresholds["large_max"]:
                flags["large_impacts"].append(max_json_object)
            elif max_abs > thresholds["moderate_max"]:
                flags["moderate_impacts"].append(max_json_object)

        else:
            print(f"{freq_key:>7} | No valid data")
            results[freq_key] = None
    
    # Save updated flags to JSON
    with open(flags_file, 'w') as f:
        json.dump(flags, f, indent=2)
    
    print("\n"*2)
    return results


def verify_additive_effects(gain_results, sa_results, eba_results, sound_speed_results, absorption_results, combined_results):
    """
    Verify that individual parameter effects add up to the combined effect.
    
    Parameters:
    -----------
    gain_results : dict
        Results from gain correction effect calculation
    sa_results : dict  
        Results from SA correction effect calculation
    eba_results : dict
        Results from equivalent beam angle effect calculation
    sound_speed_results : dict
        Results from sound speed effect calculation
    absorption_results : dict
        Results from absorption effect calculation
    combined_results : dict
        Results from combined effect calculation
        
    Returns:
    --------
    verification_results : dict
        Dictionary containing verification statistics for each frequency
    """
    
    print("="*80)
    print("\nVERIFICATION: DO INDIVIDUAL EFFECTS ADD UP TO COMBINED EFFECT?")
    print("="*80)
    print()
    
    verification_results = {}
    
    # Get all frequency keys from combined results
    freq_keys = [key for key in combined_results.keys() if combined_results[key] is not None]
    
    if not freq_keys:
        print("No valid frequency data found in combined results.")
        return verification_results
    
    print("Frequency | Individual Sum | Combined Effect | Difference | Percent Error")
    print("-" * 75)
    
    for freq_key in freq_keys:
        try:
            # Extract mean effects for this frequency from each parameter
            individual_effects = []
            effect_names = []
            
            # Check each individual result and collect valid effects
            if gain_results.get(freq_key) is not None:
                individual_effects.append(gain_results[freq_key]['mean'])
                effect_names.append('gain')
            
            if sa_results.get(freq_key) is not None:
                individual_effects.append(sa_results[freq_key]['mean'])
                effect_names.append('sa')
                
            if eba_results.get(freq_key) is not None:
                individual_effects.append(eba_results[freq_key]['mean'])
                effect_names.append('eba')
                
            if sound_speed_results.get(freq_key) is not None:
                individual_effects.append(sound_speed_results[freq_key]['mean'])
                effect_names.append('sound_speed')
                
            if absorption_results.get(freq_key) is not None:
                individual_effects.append(absorption_results[freq_key]['mean'])
                effect_names.append('absorption')
            
            # Calculate sum of individual effects
            individual_sum = sum(individual_effects)
            
            # Get combined effect
            combined_effect = combined_results[freq_key]['mean']
            
            # Calculate difference and percent error
            difference = combined_effect - individual_sum
            percent_error = (difference / combined_effect * 100) if combined_effect != 0 else float('inf')
            
            # Store results
            verification_results[freq_key] = {
                'individual_sum': individual_sum,
                'combined_effect': combined_effect,
                'difference': difference,
                'percent_error': percent_error,
                'individual_effects': dict(zip(effect_names, individual_effects)),
                'n_individual_params': len(individual_effects)
            }
            
            # Print results
            print(f"{freq_key:>8} | {individual_sum:+13.3f} | {combined_effect:+14.3f} | {difference:+10.3f} | {percent_error:+12.2f}%")
            
        except Exception as e:
            print(f"{freq_key:>8} | Error: {e}")
            verification_results[freq_key] = None
    
    print()
    
    # Summary analysis
    valid_verifications = [v for v in verification_results.values() if v is not None]
    
    if valid_verifications:
        avg_percent_error = np.mean([abs(v['percent_error']) for v in valid_verifications])
        max_percent_error = max([abs(v['percent_error']) for v in valid_verifications])
        
        print("SUMMARY:")
        print(f"  Average absolute percent error: {avg_percent_error:.2f}%")
        print(f"  Maximum absolute percent error: {max_percent_error:.2f}%")
        
        # Determine if effects are approximately additive
        tolerance = 5.0  # 5% tolerance
        if max_percent_error <= tolerance:
            print(f"  VERIFICATION PASSED: Effects are approximately additive (within {tolerance}% tolerance)")
        else:
            print(f"  VERIFICATION FAILED: Effects are NOT approximately additive (exceeds {tolerance}% tolerance)")
            
        print()
        
        # Detailed breakdown for frequencies with significant errors
        significant_errors = [freq for freq, v in verification_results.items() 
                            if v is not None and abs(v['percent_error']) > tolerance]
        
        if significant_errors:
            print("FREQUENCIES WITH SIGNIFICANT NON-ADDITIVE BEHAVIOR:")
            for freq_key in significant_errors:
                v = verification_results[freq_key]
                print(f"  {freq_key}:")
                print(f"    Combined effect: {v['combined_effect']:+.3f} dB")
                print(f"    Individual sum:  {v['individual_sum']:+.3f} dB")
                print(f"    Difference:      {v['difference']:+.3f} dB ({v['percent_error']:+.2f}%)")
                print(f"    Individual breakdown:")
                for param, effect in v['individual_effects'].items():
                    print(f"      {param}: {effect:+.3f} dB")
                print()
    else:
        print("No valid verification data available.")
    
    print("="*80)
    print()
    
    return verification_results


def compare_calibration_parameters(report_cal_params, report_env_params, report_other_params, original_cal_params, original_env_params, original_other_params, echodata):
    """Compare calibration parameters between .cal file and original netCDF values."""
    
    # Define units and formatting for all parameters
    units = {
        "sound_speed": echodata["Environment"].sound_speed_indicative[0][0].units,
        "sound_absorption": echodata["Environment"].absorption_indicative[0][0].units,
        "equivalent_beam_angle": "dB re sr",
        "gain_correction": echodata["Sonar/Beam_group1"].gain_correction.units,
        "sa_correction": "dB",
        "beamwidth_athwartship": "deg",
        "beamwidth_alongship": "deg",
        "angle_offset_athwartship": "deg",
        "angle_offset_alongship": "deg",
        "angle_sensitivity_athwartship": "unitless",
        "angle_sensitivity_alongship": "unitless",
        "transmit_power": echodata["Sonar/Beam_group1"]["transmit_power"][0][0].units,
        "transmit_bandwidth": echodata["Sonar/Beam_group1"]["transmit_bandwidth"][0][0].units,
        "sample_interval": echodata["Sonar/Beam_group1"]["sample_interval"][0][0].units,
        "transmit_duration_nominal": echodata["Sonar/Beam_group1"]["transmit_duration_nominal"][0][0].units
    }
    
    formatting = {
        "sound_speed": 1, "sound_absorption": 6, "equivalent_beam_angle": 1,
        "gain_correction": 4, "sa_correction": None, "beamwidth_athwartship": 2,
        "beamwidth_alongship": 2, "angle_offset_athwartship": 2, "angle_offset_alongship": 2,
        "angle_sensitivity_athwartship": 2, "angle_sensitivity_alongship": 2,
        "transmit_power": 1, "transmit_bandwidth": 1, "sample_interval": 6, "transmit_duration_nominal": 6
    }
    
    def extract_values(val):
        """Extract values from various data types."""
        if hasattr(val, 'values'):
            val = val.values
        if isinstance(val, np.ndarray):
            return val.flatten()
        elif hasattr(val, '__iter__') and not isinstance(val, str):
            return np.array(list(val))
        else:
            return np.array([val])
    
    def format_value(value, param_name):
        """Format value based on parameter type."""
        decimals = formatting.get(param_name)
        return round(value, decimals) if decimals is not None else value
    
    def create_channel_table(file_vals, orig_vals, param_name, channels, units_str):
        """Create a table format for multi-channel parameters."""
        max_len = max(len(file_vals), len(orig_vals))
        headers = []
        col_width = 12

        if max_len > 1:
            # Create column headers
            for i in range(max_len):
                if i < len(channels):
                    parts = str(channels[i]).split()
                    headers.append(f"{parts[0]} {parts[1]} {parts[2]}" if len(parts) >= 3 else str(channels[i])[:12])
                else:
                    headers.append(f"Ch{i+1}")
            
            col_width = max(max(len(h) for h in headers), 12)
        
        # Print table
        rows = [
            ("", headers),
            ("-"*20, ["-"*col_width]*max_len),
            ("Original (.nc)", [format_value(float(orig_vals[i]), param_name) if i < len(orig_vals) else "Missing" for i in range(max_len)]),
            ("Report (.cal)", [format_value(float(file_vals[i]), param_name) if i < len(file_vals) else "Missing" for i in range(max_len)]),  # Apply formatting here too
            ("Difference", [format_value(round(float(file_vals[i]) - float(orig_vals[i]), 10), param_name) if i < min(len(file_vals), len(orig_vals)) else "--" for i in range(max_len)]),
            ("Percent Change (%)", []),
            ("Units", [units_str]*max_len)
        ]
        
        # Calculate percent changes
        for i in range(max_len):
            if i < len(file_vals) and i < len(orig_vals):
                file_val, orig_val = float(file_vals[i]), float(orig_vals[i])
                if abs(orig_val) < 1e-8:
                    rows[5][1].append("NA")
                else:
                    percent_change = ((file_val - orig_val) / orig_val) * 100
                    if np.isinf(percent_change) or np.isnan(percent_change) or abs(percent_change) > 1e4:
                        rows[5][1].append("NA")
                    elif abs(percent_change) < 0.01:
                        rows[5][1].append("0.00%")
                    else:
                        rows[5][1].append(f"{percent_change:.2f}%")
            else:
                rows[5][1].append("--")
        
        # Print formatted table
        for label, values in rows:
            print(f"  {label:20}", end="")
            for val in values:
                print(f"{val:>{col_width}}", end="  ")
            print()

    print("="*80)
    print("CALIBRATION PARAMETER COMPARISON")
    print("="*80)
    print()
    
    # Define parameters to compare
    comparisons = [
        ("sound_speed", report_env_params, original_env_params, "Environmental"),
        ("sound_absorption", report_env_params, original_env_params, "Environmental"), 
        ("equivalent_beam_angle", report_cal_params, original_cal_params, "Calibration"),
        ("gain_correction", report_cal_params, original_cal_params, "Calibration"),
        ("sa_correction", report_cal_params, original_cal_params, "Calibration"),
        ("beamwidth_athwartship", report_cal_params, original_cal_params, "Calibration"),
        ("beamwidth_alongship", report_cal_params, original_cal_params, "Calibration"),
        ("angle_offset_athwartship", report_cal_params, original_cal_params, "Calibration"),
        ("angle_offset_alongship", report_cal_params, original_cal_params, "Calibration"),
        ("angle_sensitivity_athwartship", report_cal_params, original_cal_params, "Calibration"),
        ("angle_sensitivity_alongship", report_cal_params, original_cal_params, "Calibration"),
        
        # NOTE: the following parameters shouldn't be applied from the cal report, because the raw file is the source of truth
        # ("transmit_power", report_other_params, original_other_params, "Other"),
        # ("transmit_bandwidth", report_other_params, original_other_params, "Other"),
        # ("transmit_duration_nominal", report_other_params, original_other_params, "Other"),
        # ("sample_interval", report_other_params, original_other_params, "Other"),
    ]
    
    # Compare numerical parameters
    for param_name, file_params, orig_params, param_type in comparisons:
        print(f"\n{param_name}")
        print("-" * 50)
        
        file_exists, orig_exists = param_name in file_params, param_name in orig_params
        
        if file_exists and orig_exists:
            file_vals = extract_values(file_params[param_name])
            orig_vals = extract_values(orig_params[param_name])
            create_channel_table(file_vals, orig_vals, param_name,
                                original_other_params.get('channel', []), units.get(param_name, ""))
        else:
            print(f"  Original (.nc):  {'Present' if orig_exists else 'Missing'}")
            print(f"  Report (.cal):     {'Present' if file_exists else 'Missing'}")
            if file_exists and not orig_exists:
                print(f"  Report value:      {file_params[param_name]}")
            elif not file_exists and orig_exists:
                print(f"  Original value:  {orig_params[param_name]}")
        print()

    print("\n" + "="*80)
    print("OTHER PARAMETER COMPARISON (String Parameters)")
    print("="*80)
    print()
    
    # Compare string parameters (excluding report-specific ones)
    string_params = ["sonar_software_version", "channel", "transducer"]
    available_params = [p for p in string_params if p in report_other_params or p in original_other_params]
    
    for param_name in available_params:
        print(f"\n{param_name}")
        print("-" * 50)
        
        file_exists, orig_exists = param_name in report_other_params, param_name in original_other_params
        
        if file_exists and orig_exists:
            file_val = report_other_params[param_name]
            orig_val = original_other_params[param_name]
            
            # Convert to lists if iterable but not string
            if hasattr(orig_val, '__iter__') and not isinstance(orig_val, str):
                orig_val = orig_val if isinstance(orig_val, list) else list(orig_val)
            if hasattr(file_val, '__iter__') and not isinstance(file_val, str):
                file_val = file_val if isinstance(file_val, list) else list(file_val)
                
            print(f"  Original (.nc):  {orig_val}")
            print(f"  Report (.cal):     {file_val}")
            print(f"  Status:          {'Match' if str(orig_val) == str(file_val) else 'Different'}")
        else:
            print(f"  Original (.nc):  {'Present' if orig_exists else 'Missing'}")
            print(f"  Report (.cal):     {'Present' if file_exists else 'Missing'}")
            if file_exists and not orig_exists:
                print(f"  Report value:      {report_other_params[param_name]}")
            elif not file_exists and orig_exists:
                print(f"  Original value:  {original_other_params[param_name]}")
        print()

    print("\n" + "="*80)
    print("CALIBRATION REPORT SPECIFIC PARAMETERS")
    print("="*80)
    print()
    
    # Display report-specific parameters without comparison
    report_specific_params = ["date", "comments"]
    for param_name in report_specific_params:
        if param_name in report_other_params:
            print(f"\n{param_name}")
            print("-" * 50)
            print(f"  Report value: {report_other_params[param_name]}")
            print()
    
    print("="*80)


def perform_range_analysis(ds_Sv_baseline, ds_Sv_calibrated, echodata, title):
    """Perform range-dependent analysis of calibration parameter effects.
    
    Analyzes how calibration parameter effects vary with depth/range by comparing
    baseline and calibrated Sv values at multiple depth samples. This is particularly
    useful for understanding range-dependent effects like absorption.
    
    Args:
        ds_Sv_baseline: Baseline Sv dataset
        ds_Sv_calibrated: Calibrated Sv dataset to compare
        echodata: EchoData object for frequency information
        title (str): Title for the analysis output
    """
    # RANGE DEPENDENCY ANALYSIS
    print("="*90)
    print(f"         {title}")
    print("="*90)

    # Test at multiple range samples to show how absorption effects grow with distance
    test_range_samples = [50, 200, 400, 600, 800]  # range_sample indices to test (not actual depth)

    for range_idx in test_range_samples:
        echo_range_coord = ds_Sv_baseline.echo_range
        actual_depth = float(echo_range_coord.isel(channel=0, ping_time=0, range_sample=range_idx).values)

        print(f"\n Depth: {actual_depth:.1f} meters:")
        print("-" * 50)
        
        try:
            # Calculate mean across all pings for this range sample
            baseline_range_sample = ds_Sv_baseline["Sv"].isel(range_sample=range_idx).mean(dim=['ping_time'])
            calibrated_range_sample = ds_Sv_calibrated["Sv"].isel(range_sample=range_idx).mean(dim=['ping_time'])
            
            print("Freq     | Baseline Sv | Abs Test Sv  | Sv Change ")
            print("-" * 70)
            
            # Get channel information from echodata
            frequencies = echodata["Sonar/Beam_group1"]["frequency_nominal"].values
            
            for ch_idx in range(len(frequencies)):
                freq = float(frequencies[ch_idx])
                freq_key = f"{freq/1000:.0f}kHz"
                
                baseline_val = float(baseline_range_sample.isel(channel=ch_idx).values)
                calibrated_val = float(calibrated_range_sample.isel(channel=ch_idx).values)
                sv_diff = calibrated_val - baseline_val
                
                print(f"{freq_key:>7} | {baseline_val:10.3f} | {calibrated_val:11.3f} | {sv_diff:+8.3f}")
            
        except Exception as e:
            print(f"  Error at sample index {range_idx}: {e}")
            print("    (Sample index may be beyond available data)")


def sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_calibrated, title):
    """
    Create detailed difference analysis plots comparing baseline and calibrated Sv data.
    
    Parameters:
    -----------
    ds_Sv_baseline : xarray.Dataset
        Baseline Sv dataset
    ds_Sv_combined_test : xarray.Dataset  
        Calibrated Sv dataset to compare against baseline
    frequency_nominal : list
        List of nominal frequencies
    """
    frequency_nominal = ds_Sv_baseline["frequency_nominal"]

    # Check for frequencies with all NaN data
    sv_data_temp = ds_Sv_calibrated['Sv']
    valid_freq_indices = []
    
    for freq_idx in range(len(frequency_nominal)):
        freq_diff = sv_data_temp.isel(channel=freq_idx)
        has_valid_data = np.any(~np.isnan(freq_diff.values))
        
        if not has_valid_data:
            freq_khz = int(frequency_nominal[freq_idx].values / 1000)
            print(f"WARNING: {freq_khz} kHz has ALL NaN values - skipping this frequency in plots")
        else:
            valid_freq_indices.append(freq_idx)
    
    # Filter to only valid frequencies
    frequency_nominal = frequency_nominal[valid_freq_indices]

    # Create focused plots showing summary statistics and distribution
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Set up common variables
    freq_names = [f'{int(f/1000)} kHz' for f in frequency_nominal] 
    sv_diff_data = (ds_Sv_calibrated['Sv'] - ds_Sv_baseline['Sv']).isel(channel=valid_freq_indices)

    # Plot 1: Summary statistics across all data
    # NOTE: This uses the FULL DATASET for statistical calculations
    ax1 = axes[0]
    freq_names = [f'{int(f/1000)} kHz' for f in frequency_nominal]
    mean_diffs = []
    std_diffs = []
    max_abs_diffs = []

    for freq_idx in range(len(frequency_nominal)):
        freq_diff = sv_diff_data.isel(channel=freq_idx)
        mean_diffs.append(float(freq_diff.mean().values))
        std_diffs.append(float(freq_diff.std().values))
        max_abs_diffs.append(float(np.abs(freq_diff).max().values))

    x_pos = np.arange(len(freq_names))
    width = 0.25

    bars1 = ax1.bar(x_pos - width, mean_diffs, width, label='Mean Difference', alpha=0.8)
    bars2 = ax1.bar(x_pos, std_diffs, width, label='Std Dev', alpha=0.8)
    bars3 = ax1.bar(x_pos + width, max_abs_diffs, width, label='Max |Difference|', alpha=0.8)

    ax1.set_xlabel('Frequency', fontsize=12)
    ax1.set_ylabel('Sv Difference (dB)', fontsize=12)
    ax1.set_title('Summary Statistics by Frequency', fontsize=14, fontweight='bold')
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(freq_names)
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.axhline(y=0, color='black', linestyle=':', alpha=0.5)

    # Add value labels on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax1.annotate(f'{height:.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    # Plot 2: Histogram of differences
    ax2 = axes[1]
    colors = ['blue', 'green', 'orange', 'red']
    for freq_idx, (freq_label, color) in enumerate(zip(freq_names, colors)):
        freq_diff = sv_diff_data.isel(channel=freq_idx)
        valid_diff = freq_diff.values[~np.isnan(freq_diff.values)].flatten()
        
        ax2.hist(valid_diff, bins=50, alpha=0.6, label=freq_label, color=color, density=True)

    ax2.set_xlabel('Sv Difference (CAL - Baseline) (dB)', fontsize=12)
    ax2.set_ylabel('Probability Density', fontsize=12)
    ax2.set_title('Distribution of Sv Differences', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.axvline(x=0, color='black', linestyle=':', alpha=0.5)

    plt.tight_layout()
    plt.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
    plt.show()

