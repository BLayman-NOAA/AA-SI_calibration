"""Calibration comparison and Sv impact analysis.

Provides functions for comparing calibration parameters, computing
calibrated Sv datasets, calculating statistical effects of individual
parameters, and verifying that effects are additive.
"""

import echopype as ep
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import json
import os
from aa_si_utils import utils
from aa_si_visualization import assorted


def calculate_full_dataset_effect(ds_modified, ds_baseline, parameter_name, output_logs_folder, thresholds=None):
    """Calculate the statistical effect of a calibration parameter across the entire dataset.
    
    Computes statistics on the difference between modified and baseline Sv datasets,
    providing comprehensive analysis of how a calibration parameter affects the data.
    
    Args:
        ds_modified: Sv dataset with modified calibration parameter
        ds_baseline: Baseline Sv dataset for comparison
        parameter_name (str): Name of the parameter being analyzed for display
        output_logs_folder: Path to folder for saving log files
        thresholds (dict, optional): Thresholds for flagging impacts
        
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
    """Verify that individual parameter effects add up to the combined effect.

    Args:
        gain_results: Results from gain correction effect calculation.
        sa_results: Results from SA correction effect calculation.
        eba_results: Results from equivalent beam angle effect calculation.
        sound_speed_results: Results from sound speed effect calculation.
        absorption_results: Results from absorption effect calculation.
        combined_results: Results from combined effect calculation.

    Returns:
        dict: Verification statistics for each frequency.
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


def compare_calibration_parameters(report_params, original_params, echodata):
    """Compare calibration parameters between .cal file and original netCDF values.

    Args:
        report_params: Consolidated parameters dict from calibration report with keys
            cal_params, env_params, other_params.
        original_params: Consolidated parameters dict from original netCDF with keys
            cal_params, env_params, other_params.
        echodata: Echopype EchoData object for unit extraction.
    """
    report_cal_params = report_params["cal_params"]
    report_env_params = report_params["env_params"]
    report_other_params = report_params["other_params"]
    original_cal_params = original_params["cal_params"]
    original_env_params = original_params["env_params"]
    original_other_params = original_params["other_params"]
    
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
            ("Report (.cal)", [format_value(float(file_vals[i]), param_name) if i < len(file_vals) else "Missing" for i in range(max_len)]),
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
    """Create difference analysis plots comparing baseline and calibrated Sv data.

    Args:
        ds_Sv_baseline: Baseline Sv dataset.
        ds_Sv_calibrated: Calibrated Sv dataset to compare against baseline.
        title: Title for the plot.
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
        
        data_range = np.ptp(valid_diff) if len(valid_diff) > 0 else 0
        if len(valid_diff) == 0 or data_range == 0:
            ax2.axvline(x=valid_diff[0] if len(valid_diff) > 0 else 0,
                        color=color, alpha=0.6, label=f'{freq_label} (constant)')
        else:
            # Compute safe number of bins: ensure each bin spans at least
            # a representable float width to avoid "too many bins" errors
            max_bins = max(1, int(data_range / (np.finfo(float).eps * max(1, abs(valid_diff.mean())) * 1e6)))
            n_bins = min(50, max_bins)
            ax2.hist(valid_diff, bins=n_bins, alpha=0.6, label=freq_label, color=color, density=True)

    ax2.set_xlabel('Sv Difference (CAL - Baseline) (dB)', fontsize=12)
    ax2.set_ylabel('Probability Density', fontsize=12)
    ax2.set_title('Distribution of Sv Differences', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.axvline(x=0, color='black', linestyle=':', alpha=0.5)

    plt.tight_layout()
    plt.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
    plt.show()


def compute_calibrated_sv_datasets(echodata, report_params):
    """Compute Sv datasets with individual and combined calibration parameters.

    Args:
        echodata: Echopype EchoData object.
        report_params: Consolidated calibration parameters dict with keys
            cal_params, env_params, other_params.

    Returns:
        dict: Dictionary of unmasked Sv datasets keyed by parameter name:
            - gain: Sv with gain_correction only
            - sa: Sv with sa_correction only
            - eba: Sv with equivalent_beam_angle only
            - sound_speed: Sv with sound_speed only
            - absorption: Sv with sound_absorption only
            - combined: Sv with all parameters applied
    """
    report_cal_params = report_params["cal_params"]
    report_env_params = report_params["env_params"]

    sv_datasets = {}

    sv_datasets["gain"] = ep.calibrate.compute_Sv(
        echodata, cal_params={"gain_correction": report_cal_params["gain_correction"]}
    )
    sv_datasets["sa"] = ep.calibrate.compute_Sv(
        echodata, cal_params={"sa_correction": report_cal_params["sa_correction"]}
    )
    sv_datasets["eba"] = ep.calibrate.compute_Sv(
        echodata, cal_params={"equivalent_beam_angle": report_cal_params["equivalent_beam_angle"]}
    )
    sv_datasets["sound_speed"] = ep.calibrate.compute_Sv(
        echodata, env_params={"sound_speed": report_env_params["sound_speed"]}
    )
    sv_datasets["absorption"] = ep.calibrate.compute_Sv(
        echodata, env_params={"sound_absorption": report_env_params["sound_absorption"]}
    )

    cal_params_combined = {
        "gain_correction": report_cal_params["gain_correction"],
        "sa_correction": report_cal_params["sa_correction"],
        "equivalent_beam_angle": report_cal_params["equivalent_beam_angle"],
    }
    env_params_combined = {
        "sound_speed": report_env_params["sound_speed"],
        "sound_absorption": report_env_params["sound_absorption"],
    }
    sv_datasets["combined"] = ep.calibrate.compute_Sv(
        echodata, cal_params=cal_params_combined, env_params=env_params_combined
    )

    return sv_datasets


def run_sv_comparison_analysis(
    ds_Sv_baseline,
    calibrated_sv_datasets,
    echodata,
    original_params,
    output_logs_folder,
    sv_flag_thresholds=None,
    echogram_min_depth=0,
    echogram_max_depth=1200,
    echogram_ping_min=0,
    echogram_ping_max=1000,
):
    """Run comparison analysis between baseline and calibrated Sv datasets.

    Calculates statistical effects of each calibration parameter, generates
    diagnostic plots, performs range analysis, and verifies additive effects.

    Args:
        ds_Sv_baseline: Masked baseline Sv dataset.
        calibrated_sv_datasets: Dict of masked Sv datasets keyed by parameter name
            (gain, sa, eba, sound_speed, absorption, combined).
        echodata: Echopype EchoData object.
        original_params: Consolidated original parameters dict with keys
            cal_params, env_params, other_params.
        output_logs_folder: String or Path to folder for saving log/flag files.
        sv_flag_thresholds: Optional dict of thresholds for flagging Sv impacts.
        echogram_min_depth: Minimum depth for echogram visualization (default 0).
        echogram_max_depth: Maximum depth for echogram visualization (default 1200).
        echogram_ping_min: Minimum ping index for echogram visualization (default 0).
        echogram_ping_max: Maximum ping index for echogram visualization (default 1000).

    Returns:
        dict: Dictionary containing verification_results from additive effects check.
    """
    output_logs_folder = Path(output_logs_folder)
    original_other_params = original_params["other_params"]

    # Calculate effects of each parameter
    gain_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["gain"], ds_Sv_baseline, "Gain Correction", output_logs_folder, sv_flag_thresholds
    )
    sa_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["sa"], ds_Sv_baseline, "Sa Correction", output_logs_folder, sv_flag_thresholds
    )
    eba_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["eba"], ds_Sv_baseline, "Equivalent Beam Angle", output_logs_folder, sv_flag_thresholds
    )
    sound_speed_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["sound_speed"], ds_Sv_baseline, "Sound Speed", output_logs_folder, sv_flag_thresholds
    )
    absorption_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["absorption"], ds_Sv_baseline, "Absorption", output_logs_folder, sv_flag_thresholds
    )
    combined_results = calculate_full_dataset_effect(
        calibrated_sv_datasets["combined"], ds_Sv_baseline, "Combined Results", output_logs_folder, sv_flag_thresholds
    )

    # Plot effects
    sv_difference_summary_stats_plot(ds_Sv_baseline, calibrated_sv_datasets["absorption"], "Absorption Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, calibrated_sv_datasets["gain"], "Gain Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, calibrated_sv_datasets["sa"], "Sa Correction Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, calibrated_sv_datasets["sound_speed"], "Sound Speed Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, calibrated_sv_datasets["combined"], "Combined Differences")

    # Range analysis
    perform_range_analysis(ds_Sv_baseline, calibrated_sv_datasets["absorption"], echodata, "Absorption Effect Range Analysis")

    # Echogram visualization
    assorted.sv_differences_echograms(
        ds_Sv_baseline, calibrated_sv_datasets["combined"],
        original_other_params["frequency_nominal"],
        echogram_max_depth, echogram_min_depth,
        echogram_ping_min, echogram_ping_max,
        x_axis_units="pings", y_axis_units="meters"
    )

    # Verify additive effects
    verification_results = verify_additive_effects(
        gain_results, sa_results, eba_results,
        sound_speed_results, absorption_results, combined_results
    )

    return {"verification_results": verification_results}


def run_full_calibration_comparison(
    echodata,
    report_params,
    original_params,
    output_logs_folder,
    sv_output_folder,
    sv_flag_thresholds=None,
    mask_seafloor_buffer_m=10.0,
    mask_surface_depth_m=10.0,
    mask_frequencies=None,
    echogram_min_depth=0,
    echogram_max_depth=1200,
    echogram_ping_min=0,
    echogram_ping_max=1000,
):
    """Run the full calibration comparison pipeline.

    Compares calibration parameters, computes baseline and calibrated Sv datasets,
    calculates individual and combined parameter effects, generates diagnostic plots,
    and verifies that individual effects are additive.

    Args:
        echodata: Echopype EchoData object.
        report_params: Consolidated calibration parameters from the calibration report,
            dict with keys cal_params, env_params, other_params.
        original_params: Consolidated calibration parameters from the original netCDF,
            dict with keys cal_params, env_params, other_params.
        output_logs_folder: String or Path to folder for saving log/flag files.
        sv_output_folder: String or Path to folder for saving processed Sv data.
        sv_flag_thresholds: Optional dict of thresholds for flagging Sv impacts.
        mask_seafloor_buffer_m: Buffer in meters for seafloor mask removal (default 10.0).
        mask_surface_depth_m: Depth in meters for surface mask removal (default 10.0).
        mask_frequencies: List of frequencies (kHz) to mask (default [70, 120, 200]).
        echogram_min_depth: Minimum depth for echogram visualization (default 0).
        echogram_max_depth: Maximum depth for echogram visualization (default 1200).
        echogram_ping_min: Minimum ping index for echogram visualization (default 0).
        echogram_ping_max: Maximum ping index for echogram visualization (default 1000).

    Returns:
        dict: Dictionary containing:
            - ds_Sv_baseline: Masked baseline Sv dataset
            - ds_Sv_combined_test: Sv dataset with all calibration parameters applied
            - mask: The applied data mask
            - verification_results: Results from additive effects verification
    """

    output_logs_folder = Path(output_logs_folder)
    sv_output_folder = Path(sv_output_folder)

    report_cal_params = report_params["cal_params"]
    report_env_params = report_params["env_params"]
    report_other_params = report_params["other_params"]
    original_cal_params = original_params["cal_params"]
    original_env_params = original_params["env_params"]
    original_other_params = original_params["other_params"]

    if mask_frequencies is None:
        mask_frequencies = [70, 120, 200]

    # --- Step 2: Calculate Baseline Sv and apply masks ---
    ds_Sv = ep.calibrate.compute_Sv(echodata)

    mask_blank = utils.createSvMask(ds_Sv)
    mask_no_seafloor = utils.remove_seafloor_from_mask(
        echodata, ds_Sv, mask_blank, buffer_m=mask_seafloor_buffer_m
    )
    mask = utils.remove_surface_from_mask(
        ds_Sv, mask_no_seafloor, depth_threshold_m=mask_surface_depth_m
    )

    utils.mask_frequency_channels(ds_Sv, mask, mask_frequencies)
    utils.log_mask_stats(mask)

    ds_Sv_baseline = utils.apply_mask_to_sv(ds_Sv, mask)

    ds_Sv_baseline.to_netcdf(sv_output_folder / "NEFSC_processed_data.nc")
    print("Seafloor mask applied and saved")

    # --- Step 3: Generate Sv with individual calibration parameters ---
    # gain correction
    cal_params_gain_only = {'gain_correction': report_cal_params["gain_correction"]}
    ds_Sv_gain_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, cal_params=cal_params_gain_only), mask
    )

    # sa correction
    cal_params_sa_only = {'sa_correction': report_cal_params["sa_correction"]}
    ds_Sv_sa_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, cal_params=cal_params_sa_only), mask
    )

    # equivalent beam angle
    cal_params_eba_only = {'equivalent_beam_angle': report_cal_params["equivalent_beam_angle"]}
    ds_Sv_eba_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, cal_params=cal_params_eba_only), mask
    )

    # sound speed
    env_params_ss_only = {'sound_speed': report_env_params["sound_speed"]}
    ds_Sv_sound_speed_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, env_params=env_params_ss_only), mask
    )

    # absorption
    env_params_ab_only = {'sound_absorption': report_env_params["sound_absorption"]}
    ds_Sv_absorption_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, env_params=env_params_ab_only), mask
    )

    # combined
    cal_params_combined = {
        'gain_correction': report_cal_params["gain_correction"],
        'sa_correction': report_cal_params["sa_correction"],
        'equivalent_beam_angle': report_cal_params["equivalent_beam_angle"]
    }
    env_params_combined = {
        'sound_speed': report_env_params["sound_speed"],
        'sound_absorption': report_env_params["sound_absorption"]
    }
    ds_Sv_combined_test = utils.apply_mask_to_sv(
        ep.calibrate.compute_Sv(echodata, cal_params=cal_params_combined, env_params=env_params_combined), mask
    )

    # --- Step 4: Calculate effects of each parameter ---
    gain_results = calculate_full_dataset_effect(
        ds_Sv_gain_test, ds_Sv_baseline, "Gain Correction", output_logs_folder, sv_flag_thresholds
    )
    sa_results = calculate_full_dataset_effect(
        ds_Sv_sa_test, ds_Sv_baseline, "Sa Correction", output_logs_folder, sv_flag_thresholds
    )
    eba_results = calculate_full_dataset_effect(
        ds_Sv_eba_test, ds_Sv_baseline, "Equivalent Beam Angle", output_logs_folder, sv_flag_thresholds
    )
    sound_speed_results = calculate_full_dataset_effect(
        ds_Sv_sound_speed_test, ds_Sv_baseline, "Sound Speed", output_logs_folder, sv_flag_thresholds
    )
    absorption_results = calculate_full_dataset_effect(
        ds_Sv_absorption_test, ds_Sv_baseline, "Absorption", output_logs_folder, sv_flag_thresholds
    )
    combined_results = calculate_full_dataset_effect(
        ds_Sv_combined_test, ds_Sv_baseline, "Combined Results", output_logs_folder, sv_flag_thresholds
    )

    # --- Step 5: Plot effects ---
    sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_absorption_test, "Absorption Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_gain_test, "Gain Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_sa_test, "Sa Correction Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_sound_speed_test, "Sound Speed Differences")
    sv_difference_summary_stats_plot(ds_Sv_baseline, ds_Sv_combined_test, "Combined Differences")

    # --- Step 6: Range analysis ---
    perform_range_analysis(ds_Sv_baseline, ds_Sv_absorption_test, echodata, "Absorption Effect Range Analysis")

    # --- Step 7: Echogram visualization ---
    assorted.sv_differences_echograms(
        ds_Sv_baseline, ds_Sv_combined_test,
        original_other_params["frequency_nominal"],
        echogram_max_depth, echogram_min_depth,
        echogram_ping_min, echogram_ping_max,
        x_axis_units="pings", y_axis_units="meters"
    )

    # --- Step 8: Verify additive effects ---
    verification_results = verify_additive_effects(
        gain_results, sa_results, eba_results,
        sound_speed_results, absorption_results, combined_results
    )

    return {
        "ds_Sv_baseline": ds_Sv_baseline,
        "ds_Sv_combined_test": ds_Sv_combined_test,
        "mask": mask,
        "verification_results": verification_results,
    }
