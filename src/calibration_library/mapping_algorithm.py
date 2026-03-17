"""
Calibration Mapping Algorithm Module

This module provides functionality for matching raw file channel configurations
to their corresponding calibration data based on multiple parameters including
transceiver ID, transducer model, pulse form, frequency range, transmit power,
and transmit duration.

Example usage:
    from calibration_library.mapping_algorithm import (
        load_raw_configs, load_calibration_data, build_mapping,
        get_calibration, save_mapping_files
    )
    
    # Load data
    raw_configs = load_raw_configs("path/to/raw_configs.yaml")
    cal_data = load_calibration_data("path/to/calibration.yml")
    
    # Build mapping
    result = build_mapping(raw_configs, cal_data)
    
    # Get calibration for a specific file and channel
    cal = get_calibration("filename.raw", "channel_id", result.mapping_dict, result.calibration_dict)
"""

import shutil
import yaml
import datetime
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default numerical tolerances for field comparisons
DEFAULT_TOLERANCES = {
    'frequency': 1.0,              # Hz - exact match expected
    'frequency_start': 1.0,        # Hz - exact match expected  
    'frequency_end': 1.0,          # Hz - exact match expected
    'transmit_power': 1.0,         # Watts - exact match expected
    'transmit_duration_nominal': 1e-6,  # seconds - small tolerance for floating point
}

# Import string identifier conversion from standardized_file_lib
from .standardized_file_lib import ensure_string_identifiers as _ensure_string_identifiers

# Import unified calibration key, filename, and file I/O functions.
# These are the single source of truth; this module re-exports them for
# backward compatibility.
from .standardized_file_lib import (
    build_calibration_key,
    calibration_key_to_filename,
    get_calibration_from_file,
    save_individual_calibration_files as _save_individual_calibration_files_impl,
    remap_to_short_keys,
    _strip_internal_keys,
    _StandardizedFileDumper,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class UnmatchedChannel:
    """Represents a channel that could not be matched to calibration data."""
    filename: str
    channel_id: str


@dataclass
class MultipleMatchChannel:
    """Represents a channel with multiple calibration matches."""
    filename: str
    channel_id: str
    match_count: int
    matching_cal_keys: List[str] = field(default_factory=list)


@dataclass
class MultiplexingWarning:
    """Represents a multiplexing warning for a channel."""
    filename: str
    channel_id: str
    warning: str


@dataclass
class MappingResult:
    """
    Contains the results of the calibration mapping process.
    
    Attributes:
        mapping_dict: Maps filename -> channel_id -> calibration_key
        calibration_dict: Maps calibration_key -> calibration data object
        total_channels: Total number of file channels processed (across all files)
        matched_channels: Number of successfully matched file channels
        unique_raw_channels: Number of distinct raw channel configurations
        unique_matched_channels: Number of distinct raw channel configurations that matched
        unmatched_channels: List of channels that could not be matched
        multiple_matches: List of channels with multiple matches
        multiplexing_warnings: List of multiplexing warnings
    """
    mapping_dict: Dict[str, Dict[str, str]] = field(default_factory=dict)
    calibration_dict: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_channels: int = 0
    matched_channels: int = 0
    unique_raw_channels: int = 0
    unique_matched_channels: int = 0
    total_calibrations_loaded: int = 0
    unmatched_channels: List[UnmatchedChannel] = field(default_factory=list)
    multiple_matches: List[MultipleMatchChannel] = field(default_factory=list)
    multiplexing_warnings: List[MultiplexingWarning] = field(default_factory=list)

    def print_summary(self):
        """Print a summary of the mapping results."""
        # Count unique raw configurations with multiple calibration matches
        from collections import defaultdict as _defaultdict
        _groups = _defaultdict(list)
        for mm in self.multiple_matches:
            key = tuple(sorted(mm.matching_cal_keys))
            _groups[key].append(mm)
        unique_conflicts = len(_groups)

        print(f"\n{'='*60}")
        print("MATCHING SUMMARY")
        print(f"{'='*60}")
        print(f"\nRaw file channels:")
        print(f"  Total file channels processed: {self.total_channels}")
        print(f"  Total unique channels: {self.unique_raw_channels}")
        print(f"  Matched file channels: {self.matched_channels}")
        print(f"  Matched unique channels: {self.unique_matched_channels}")
        print(f"  Unmatched file channels: {len(self.unmatched_channels)}")
        print(f"  Multiplexing warnings: {len(self.multiplexing_warnings)}")
        print(f"\nCalibration files:")
        print(f"  Total calibrations loaded: {self.total_calibrations_loaded}")
        print(f"  Unique calibrations used: {len(self.calibration_dict)}")
        print(f"  Conflicting calibration sets: {unique_conflicts}")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def values_match_with_tolerance(
    raw_value: Any, 
    cal_value: Any, 
    field_name: str,
    tolerances: Dict[str, float] = None
) -> bool:
    """
    Compare two numerical values with tolerance.
    
    Args:
        raw_value: Value from the raw file configuration
        cal_value: Value from the calibration data
        field_name: Name of the field (used to look up tolerance)
        tolerances: Custom tolerance dictionary (uses DEFAULT_TOLERANCES if None)
    
    Returns:
        True if values are within tolerance, False otherwise
    """
    if tolerances is None:
        tolerances = DEFAULT_TOLERANCES
    
    tolerance = tolerances.get(field_name, 0)
    
    # Handle case where calibration value might be a list (e.g., frequency)
    if isinstance(cal_value, list):
        cal_value = cal_value[0] if cal_value else None
    
    if raw_value is None or cal_value is None:
        return raw_value == cal_value
    
    return abs(float(raw_value) - float(cal_value)) <= tolerance


def frequency_range_is_valid(
    raw_freq_start: float,
    raw_freq_end: float,
    cal_freq_start: float,
    cal_freq_end: float,
    tolerances: Dict[str, float] = None
) -> bool:
    """
    Check if the raw file's frequency range is contained within the calibration's frequency range.
    
    For calibration to be valid:
    - Raw frequency_start must be >= calibration frequency_start (with tolerance)
    - Raw frequency_end must be <= calibration frequency_end (with tolerance)
    
    Args:
        raw_freq_start: Raw file frequency start
        raw_freq_end: Raw file frequency end
        cal_freq_start: Calibration frequency start
        cal_freq_end: Calibration frequency end
        tolerances: Custom tolerance dictionary
    
    Returns:
        True if raw frequency range is within calibration range, False otherwise
    """
    if tolerances is None:
        tolerances = DEFAULT_TOLERANCES
    
    tolerance = tolerances.get('frequency_start', 1.0)
    
    # Handle list values from calibration
    if isinstance(cal_freq_start, list):
        cal_freq_start = cal_freq_start[0] if cal_freq_start else None
    if isinstance(cal_freq_end, list):
        cal_freq_end = cal_freq_end[0] if cal_freq_end else None
    
    if any(v is None for v in [raw_freq_start, raw_freq_end, cal_freq_start, cal_freq_end]):
        return False
    
    raw_start = float(raw_freq_start)
    raw_end = float(raw_freq_end)
    cal_start = float(cal_freq_start)
    cal_end = float(cal_freq_end)
    
    # Raw range must be contained within calibration range (with tolerance)
    start_valid = raw_start >= (cal_start - tolerance)
    end_valid = raw_end <= (cal_end + tolerance)
    
    return start_valid and end_valid


def strings_match(raw_value: Any, cal_value: Any) -> bool:
    """
    Compare two values as strings after conversion.
    
    Args:
        raw_value: First value to compare
        cal_value: Second value to compare
    
    Returns:
        True if string representations match, False otherwise
    """
    return str(raw_value) == str(cal_value)


def check_multiplexing(raw_channel: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Check if multiplexing is enabled for the raw channel.
    
    Args:
        raw_channel: Raw channel configuration dictionary
    
    Returns:
        Tuple of (is_multiplexed, warning_message)
        - If multiplexing is found, returns (True, warning_message)
        - If no multiplexing, returns (False, None)
    """
    multiplexing_found = raw_channel.get('multiplexing_found', False)
    if multiplexing_found:
        return True, "Multiplexing is enabled - calibration may not be valid"
    return False, None


def find_matching_calibration(
    raw_channel: Dict[str, Any],
    calibration_channels: List[Dict[str, Any]],
    tolerances: Dict[str, float] = None,
    verbose: bool = False
) -> Tuple[List[Dict[str, Any]], Optional[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Find the calibration channel that matches the raw file channel configuration.
    
    Comparison order (optimized for fast elimination):
    0. multiplexing check (invalidates match if enabled)
    1. transceiver_id (unique identifier - eliminates most candidates)
    2. transducer_model (string match)
    3. transducer_serial_number (string match - skipped if either side is None/missing)
    4. pulse_form (string match - '0' or '1')
    5. frequency range (raw range must be contained within calibration range)
    6. transmit_power (numerical with tolerance)
    7. transmit_duration_nominal (numerical with tolerance)
    
    Args:
        raw_channel: Raw channel configuration dictionary
        calibration_channels: List of calibration channel dictionaries
        tolerances: Custom tolerance dictionary
        verbose: If True, collect detailed failure reasons
    
    Returns:
        Tuple of (matches, multiplexing_warning, failure_details, tsn_warnings)
        - matches: list of matching calibration channels (should be exactly 1)
        - multiplexing_warning: warning message if multiplexing is enabled
        - failure_details: list of dicts describing why each calibration didn't match
        - tsn_warnings: list of dicts for matches where transducer_serial_number
          comparison was skipped because one or both sides were None
    """
    if tolerances is None:
        tolerances = DEFAULT_TOLERANCES
    
    matches = []
    failure_details = []
    tsn_warnings = []  # Track matches where transducer_serial_number was skipped
    
    # Step 0: Check for multiplexing (still return matches but with warning)
    is_multiplexed, multiplexing_warning = check_multiplexing(raw_channel)
    
    for cal_channel in calibration_channels:
        failure_reason = None
        cal_channel_name = cal_channel.get('channel', 'Unknown')
        tsn_skipped = False
        
        # Step 1: transceiver_id (most discriminating - unique per channel)
        raw_tid = raw_channel.get('transceiver_id')
        cal_tid = cal_channel.get('transceiver_id')
        if raw_tid != cal_tid:
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'transceiver_id',
                    'raw_value': raw_tid,
                    'cal_value': cal_tid
                })
            continue
            
        # Step 2: transducer_model
        raw_tm = raw_channel.get('transducer_model')
        cal_tm = cal_channel.get('transducer_model')
        if raw_tm != cal_tm:
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'transducer_model',
                    'raw_value': raw_tm,
                    'cal_value': cal_tm
                })
            continue
        
        # Step 3: transducer_serial_number (skip if either side is None/missing)
        raw_tsn = raw_channel.get('transducer_serial_number')
        cal_tsn = cal_channel.get('transducer_serial_number')
        # Only compare if both sides have a value; warn if one side is missing
        if raw_tsn is not None and cal_tsn is not None:
            if str(raw_tsn) != str(cal_tsn):
                if verbose:
                    failure_details.append({
                        'cal_channel': cal_channel_name,
                        'failed_at': 'transducer_serial_number',
                        'raw_value': raw_tsn,
                        'cal_value': cal_tsn
                    })
                continue
        elif raw_tsn is None or cal_tsn is None:
            # One or both sides missing transducer_serial_number — proceed
            # without comparing, but track that we skipped (will warn later)
            tsn_skipped = True
            
        # Step 4: pulse_form (convert to string for comparison)
        raw_pf = raw_channel.get('pulse_form')
        cal_pf = cal_channel.get('pulse_form')
        if not strings_match(raw_pf, cal_pf):
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'pulse_form',
                    'raw_value': raw_pf,
                    'cal_value': cal_pf
                })
            continue
            
        # Step 5: frequency range (raw range must be within calibration range)
        raw_fs = raw_channel.get('frequency_start')
        raw_fe = raw_channel.get('frequency_end')
        cal_fs = cal_channel.get('frequency_start')
        cal_fe = cal_channel.get('frequency_end')
        if not frequency_range_is_valid(raw_fs, raw_fe, cal_fs, cal_fe, tolerances):
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'frequency_range',
                    'raw_value': f"[{raw_fs}, {raw_fe}]",
                    'cal_value': f"[{cal_fs}, {cal_fe}]"
                })
            continue
            
        # Step 6: transmit_power
        raw_tp = raw_channel.get('transmit_power')
        cal_tp = cal_channel.get('transmit_power')
        if not values_match_with_tolerance(raw_tp, cal_tp, 'transmit_power', tolerances):
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'transmit_power',
                    'raw_value': raw_tp,
                    'cal_value': cal_tp,
                    'tolerance': tolerances.get('transmit_power', 0)
                })
            continue
            
        # Step 7: transmit_duration_nominal
        raw_td = raw_channel.get('transmit_duration_nominal')
        cal_td = cal_channel.get('transmit_duration_nominal')
        if not values_match_with_tolerance(raw_td, cal_td, 'transmit_duration_nominal', tolerances):
            if verbose:
                failure_details.append({
                    'cal_channel': cal_channel_name,
                    'failed_at': 'transmit_duration_nominal',
                    'raw_value': raw_td,
                    'cal_value': cal_td,
                    'tolerance': tolerances.get('transmit_duration_nominal', 0)
                })
            continue
        
        # All checks passed - this is a match
        matches.append(cal_channel)
        if tsn_skipped:
            raw_tsn = raw_channel.get('transducer_serial_number')
            cal_tsn = cal_channel.get('transducer_serial_number')
            tsn_warnings.append({
                'cal_channel': cal_channel_name,
                'raw_tsn': raw_tsn,
                'cal_tsn': cal_tsn,
            })
    
    return matches, multiplexing_warning, failure_details, tsn_warnings


# build_calibration_key is imported from standardized_file_lib above.


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def load_raw_configs(file_path: str | Path) -> List[Dict[str, Any]]:
    """
    Load raw file configurations from a YAML file.
    
    Args:
        file_path: Path to the raw configs YAML file
    
    Returns:
        List of raw file configuration dictionaries
    """
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)


def load_calibration_data(file_path: str | Path) -> Dict[str, Any]:
    """
    Load calibration data from a YAML file.
    
    Args:
        file_path: Path to the calibration YAML file
    
    Returns:
        Calibration data dictionary
    """
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)


def load_calibration_data_from_single_files(
    cal_files_dir: str | Path,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Load calibration data from a directory of single-channel YAML files.
    
    Each .yml file in the directory is expected to contain a flat dictionary
    of calibration parameters for one channel (the same format produced by
    save_individual_calibration_files or save_single_channel_files).
    
    The returned dictionary has the same structure as load_calibration_data():
    ``{"channels": [<channel_dict>, ...]}`` so it can be passed directly
    to build_mapping().
    
    File names do not matter as long as they are unique and end with .yml.
    
    Args:
        cal_files_dir: Path to the directory containing single-channel .yml files
        verbose: If True, print progress messages
    
    Returns:
        Calibration data dictionary with 'channels' key containing a list
        of channel dictionaries.
    """
    cal_files_dir = Path(cal_files_dir)
    if not cal_files_dir.exists():
        raise FileNotFoundError(f"Calibration files directory not found: {cal_files_dir}")
    
    channels = []
    yml_files = sorted(cal_files_dir.glob("*.yml"))
    
    if not yml_files:
        raise FileNotFoundError(
            f"No .yml files found in {cal_files_dir}. "
            "Expected single-channel calibration YAML files."
        )
    
    for yml_file in yml_files:
        with open(yml_file, 'r') as f:
            channel_data = yaml.safe_load(f)
        
        if channel_data is None:
            if verbose:
                print(f"  Skipping empty file: {yml_file.name}")
            continue
        
        # Ensure string identifiers are consistent
        channel_data = _ensure_string_identifiers(channel_data)

        # Store the filename stem so the mapping can use it as the key
        channel_data['_calibration_file_key'] = yml_file.stem

        channels.append(channel_data)
        
        if verbose:
            freq = channel_data.get('frequency', [None])
            if isinstance(freq, list) and freq:
                freq = freq[0]
            channel_name = channel_data.get('channel', yml_file.stem)
            print(f"  Loaded: {yml_file.name} ({channel_name}, {freq} Hz)")
    
    if verbose:
        print(f"\nLoaded {len(channels)} calibration channel(s) from {cal_files_dir}")
    
    return {"channels": channels}


def _print_failure_summary(
    raw_channel: Dict[str, Any],
    failure_details: List[Dict[str, Any]],
    calibration_channels: List[Dict[str, Any]]
) -> None:
    """
    Print a summary of why a raw channel didn't match any calibration.
    
    Args:
        raw_channel: The raw channel that failed to match
        failure_details: List of failure info dicts from find_matching_calibration
        calibration_channels: List of all calibration channels
    """
    # Count failures by parameter
    failure_counts = {}
    for detail in failure_details:
        param = detail['failed_at']
        failure_counts[param] = failure_counts.get(param, 0) + 1
    
    print(f"    Raw channel values:")
    print(f"      transceiver_id: {raw_channel.get('transceiver_id')}")
    print(f"      transducer_model: {raw_channel.get('transducer_model')}")
    print(f"      transducer_serial_number: {raw_channel.get('transducer_serial_number')}")
    print(f"      pulse_form: {raw_channel.get('pulse_form')}")
    print(f"      frequency_start: {raw_channel.get('frequency_start')}")
    print(f"      frequency_end: {raw_channel.get('frequency_end')}")
    print(f"      transmit_power: {raw_channel.get('transmit_power')}")
    print(f"      transmit_duration_nominal: {raw_channel.get('transmit_duration_nominal')}")
    
    print(f"    Failure summary (why {len(calibration_channels)} calibration channel(s) didn't match):")
    
    # Show the most common failure reason first
    sorted_failures = sorted(failure_counts.items(), key=lambda x: -x[1])
    for param, count in sorted_failures:
        print(f"      - {count} failed at '{param}'")
    
    # Show the "closest" matches (ones that failed at later stages)
    # Priority order: transmit_duration_nominal > transmit_power > frequency_range > pulse_form > transducer_serial_number > transducer_model > transceiver_id
    stage_order = ['transmit_duration_nominal', 'transmit_power', 'frequency_range', 
                   'pulse_form', 'transducer_serial_number', 'transducer_model', 'transceiver_id']
    
    closest_matches = []
    for detail in failure_details:
        stage_idx = stage_order.index(detail['failed_at']) if detail['failed_at'] in stage_order else -1
        closest_matches.append((stage_idx, detail))
    
    # Sort by stage index (higher = closer to matching)
    closest_matches.sort(key=lambda x: x[0], reverse=True)
    
    if closest_matches:
        print(f"    Closest calibration matches (failed at later stage):")
        shown = 0
        for stage_idx, detail in closest_matches[:3]:  # Show top 3 closest
            print(f"      - Cal channel '{detail['cal_channel']}' failed at '{detail['failed_at']}'")
            print(f"        raw={detail['raw_value']} vs cal={detail['cal_value']}")
            if 'tolerance' in detail:
                print(f"        (tolerance: {detail['tolerance']})")
            shown += 1


def build_mapping(
    raw_file_configs: List[Dict[str, Any]],
    calibration_data: Dict[str, Any],
    tolerances: Dict[str, float] = None,
    verbose: bool = False
) -> MappingResult:
    """
    Build mapping between raw file channels and calibration data.
    
    Args:
        raw_file_configs: List of raw file configuration dictionaries
        calibration_data: Calibration data dictionary with 'channels' key
        tolerances: Custom tolerance dictionary (uses DEFAULT_TOLERANCES if None)
        verbose: If True, print progress messages
    
    Returns:
        MappingResult containing mapping_dict, calibration_dict, and statistics
    """
    result = MappingResult()
    calibration_channels = calibration_data['channels']
    result.total_calibrations_loaded = len(calibration_channels)
    unique_raw_keys = set()
    unique_matched_raw_keys = set()
    
    for raw_file in raw_file_configs:
        filename = raw_file['filename']
        result.mapping_dict[filename] = {}
        
        for raw_channel in raw_file['channels']:
            result.total_channels += 1
            channel_id = raw_channel['channel_id']
            raw_config_key = build_calibration_key(raw_channel)
            unique_raw_keys.add(raw_config_key)
            
            # Find matching calibration channel(s)
            matches, multiplexing_warning, failure_details, tsn_warnings = find_matching_calibration(
                raw_channel, calibration_channels, tolerances, verbose=verbose
            )
            
            # Track multiplexing warnings
            if multiplexing_warning:
                result.multiplexing_warnings.append(
                    MultiplexingWarning(filename, channel_id, multiplexing_warning)
                )
                if verbose:
                    print(f"  MULTIPLEXING: {filename} -> {channel_id}: {multiplexing_warning}")
            
            # Warn about missing transducer_serial_number on matched channels
            if tsn_warnings and verbose:
                for tw in tsn_warnings:
                    raw_tsn = tw['raw_tsn']
                    cal_tsn = tw['cal_tsn']
                    parts = []
                    if raw_tsn is None:
                        parts.append("raw file")
                    if cal_tsn is None:
                        parts.append("calibration file")
                    missing_side = " and ".join(parts)
                    print(
                        f"  WARNING: {filename} -> {channel_id}: "
                        f"transducer_serial_number is missing in {missing_side}. "
                        f"Matching proceeded without comparing transducer serial numbers."
                    )
            
            if len(matches) == 0:
                # No match found
                result.unmatched_channels.append(
                    UnmatchedChannel(filename, channel_id)
                )
                if verbose:
                    print(f"\n  NO MATCH: {filename} -> {channel_id}")
                    _print_failure_summary(raw_channel, failure_details, calibration_channels)
                    
            elif len(matches) > 1:
                # Multiple matches found — collect all matching keys
                match_cal_keys = []
                for m in matches:
                    ck = m.get('_calibration_file_key') or build_calibration_key(m)
                    match_cal_keys.append(ck)
                    result.calibration_dict[ck] = m

                result.multiple_matches.append(
                    MultipleMatchChannel(filename, channel_id, len(matches), match_cal_keys)
                )
                if verbose:
                    print(f"  MULTIPLE MATCHES ({len(matches)}): {filename} -> {channel_id}")
                # Use first match for the mapping (user must resolve before saving)
                result.mapping_dict[filename][channel_id] = match_cal_keys[0]
                result.matched_channels += 1
                unique_matched_raw_keys.add(raw_config_key)
                
            else:
                # Exactly one match - expected case
                match = matches[0]
                cal_key = match.get('_calibration_file_key') or build_calibration_key(match)
                result.mapping_dict[filename][channel_id] = cal_key
                result.calibration_dict[cal_key] = match
                result.matched_channels += 1
                unique_matched_raw_keys.add(raw_config_key)
    
    result.unique_raw_channels = len(unique_raw_keys)
    result.unique_matched_channels = len(unique_matched_raw_keys)
    return result


def get_calibration(
    filename: str,
    channel_id: str,
    mapping_dict: Dict[str, Dict[str, str]],
    calibration_dict: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Retrieve calibration data for a specific raw file and channel.
    
    Args:
        filename: Raw file name (e.g., 'D20160725-T205832.raw')
        channel_id: Channel ID (e.g., 'GPT  38 kHz 0090720346bc 1-1 ES38B')
        mapping_dict: The mapping dictionary
        calibration_dict: The calibration dictionary
    
    Returns:
        Calibration data object or None if not found
    """
    if filename not in mapping_dict:
        return None
    
    if channel_id not in mapping_dict[filename]:
        return None
    
    cal_key = mapping_dict[filename][channel_id]
    return calibration_dict.get(cal_key)


# get_calibration_from_file is imported from standardized_file_lib above.


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================

def save_mapping_files(
    result: MappingResult,
    output_dir: str | Path,
    mapping_filename: str = "channel_to_calibration_mapping.yaml",
    calibration_filename: str = "calibration_configurations.yaml",
    short_filenames: bool = False,
) -> Tuple[Path, Path]:
    """
    Save mapping and calibration dictionaries to YAML files.
    
    When *short_filenames* is ``True``, the long internal calibration keys
    are remapped to compact identifiers (e.g.
    ``2016-07-03__38000__config-1``) in both the mapping and calibration
    output files.

    Args:
        result: MappingResult from build_mapping()
        output_dir: Directory to save output files
        mapping_filename: Name for the mapping file
        calibration_filename: Name for the calibration file
        short_filenames: If ``True``, use compact short identifiers as
            keys in the output files.
    
    Returns:
        Tuple of (mapping_file_path, calibration_file_path)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate a shared timestamp for all calibrations that don't have one
    shared_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Ensure all calibration entries have record_created set
    for cal_key, cal_data in result.calibration_dict.items():
        if cal_data.get('record_created') is None:
            cal_data['record_created'] = shared_timestamp
    
    # Remap to short keys if requested
    if short_filenames:
        # If the keys already came from single-channel filenames (i.e.
        # _calibration_file_key matches the dict key for every entry),
        # they are already short — skip re-remapping which would
        # incorrectly renumber them after unused files were deleted.
        keys_already_short = all(
            cd.get('_calibration_file_key') == ck
            for ck, cd in result.calibration_dict.items()
        )
        if keys_already_short:
            mapping_to_save = result.mapping_dict
            calibration_to_save = result.calibration_dict
        else:
            mapping_to_save, calibration_to_save, _ = remap_to_short_keys(
                result.mapping_dict, result.calibration_dict
            )
    else:
        mapping_to_save = result.mapping_dict
        calibration_to_save = result.calibration_dict

    # Ensure identifier fields are stored as strings
    # Strip internal tracking keys before writing
    calibration_dict_cleaned = {
        k: _strip_internal_keys(v)
        for k, v in _ensure_string_identifiers(calibration_to_save).items()
    }
    
    # Save mapping dictionary
    mapping_path = output_dir / mapping_filename
    with open(mapping_path, 'w') as f:
        yaml.dump(mapping_to_save, f, default_flow_style=False, sort_keys=False)
    
    # Save calibration dictionary
    calibration_path = output_dir / calibration_filename
    with open(calibration_path, 'w') as f:
        yaml.dump(calibration_dict_cleaned, f, Dumper=_StandardizedFileDumper, default_flow_style=False, sort_keys=False)
    
    return mapping_path, calibration_path


def save_individual_calibration_files(
    result: MappingResult,
    output_dir: str | Path,
    short_filenames: bool = False,
) -> int:
    """
    Save each calibration as a separate YAML file named by its key.

    Convenience wrapper around
    :func:`standardized_file_lib.save_individual_calibration_files` that
    accepts a :class:`MappingResult` directly.

    Args:
        result: MappingResult from build_mapping()
        output_dir: Directory to save individual calibration files
        short_filenames: If ``True``, use compact
            ``<date>__<freq>__config-<N>`` naming scheme.

    Returns:
        Number of files saved
    """
    return _save_individual_calibration_files_impl(
        result.calibration_dict, output_dir, short_filenames=short_filenames
    )


def print_mapping_preview(result: MappingResult):
    """
    Print a preview of the mapping dictionary.
    
    Args:
        result: MappingResult from build_mapping()
    """
    print("MAPPING DICTIONARY PREVIEW")
    print("=" * 60)
    for filename, channels in result.mapping_dict.items():
        print(f"\n{filename}:")
        for channel_id, cal_key in channels.items():
            print(f"  {channel_id}")
            print(f"    -> {cal_key}")
    
    print(f"\n\nCALIBRATION DICTIONARY KEYS")
    print("=" * 60)
    for cal_key in result.calibration_dict.keys():
        print(f"  {cal_key}")


# =============================================================================
# MANUAL PIPELINE: Deterministic Mapping (no matching algorithm)
# =============================================================================

def build_mapping_from_raw_configs(
    file_configs: List[Dict[str, Any]],
    calibration_date: str,
) -> Dict[str, Dict[str, str]]:
    """
    Build a mapping dictionary directly from raw file configurations.

    Unlike :func:`build_mapping`, this does **not** run the matching algorithm.
    It is used in the *manual* pipeline where each raw channel maps
    deterministically to the calibration template that shares the same key
    (the key encodes the calibration date + channel parameters).

    Args:
        file_configs: List of raw file configuration dicts (as returned by
            ``extract_ek60_file_config`` / ``extract_ek80_file_config``).
        calibration_date: User-provided calibration date string used for
            building channel keys.

    Returns:
        Mapping dictionary: ``filename -> channel_id -> calibration_key``.
    """
    mapping: Dict[str, Dict[str, str]] = {}

    for file_config in file_configs:
        filename = file_config.get('filename')
        mapping[filename] = {}

        for channel in file_config.get('channels', []):
            channel_id = channel.get('channel_id')
            cal_key = build_calibration_key(channel, calibration_date)
            mapping[filename][channel_id] = cal_key

    return mapping


# =============================================================================
# REQUIRED CALIBRATION PARAMETER DEFINITIONS
# =============================================================================

REQUIRED_CALIBRATION_PARAMS = [
    "calibration_date",
    "gain_correction",
    "sa_correction",
    "equivalent_beam_angle",
    "beamwidth_transmit_major",
    "beamwidth_receive_major",
    "beamwidth_transmit_minor",
    "beamwidth_receive_minor",
    "echoangle_major",
    "echoangle_minor",
]

# Environmental: either direct values or T/S/P to derive them
ENVIRONMENTAL_DIRECT = ["absorption_indicative", "sound_speed_indicative"]
ENVIRONMENTAL_DERIVED = ["temperature", "salinity", "pressure"]


# =============================================================================
# HIGH-LEVEL PIPELINE FUNCTIONS
# =============================================================================

def _is_missing(value: Any) -> bool:
    """Return True if a parameter value is effectively missing (None or all-None list)."""
    if value is None:
        return True
    if isinstance(value, list):
        return all(v is None for v in value)
    return False


def _remove_or_move_file(cal_file_path: Path, keep: bool, unused_dir: Path = None):
    """Delete or move a calibration file.
    
    Args:
        cal_file_path: Path to the calibration file.
        keep: If True, move the file to *unused_dir*; otherwise delete it.
        unused_dir: Destination directory when *keep* is True.
    """
    if keep:
        if unused_dir is None:
            raise ValueError("unused_dir is required when keep=True")
        unused_dir.mkdir(parents=True, exist_ok=True)
        dest = unused_dir / cal_file_path.name
        shutil.move(str(cal_file_path), str(dest))
    else:
        cal_file_path.unlink()


def handle_unused_calibration_files(
    result: MappingResult,
    calibration_data: Dict[str, Any],
    cal_files_dir: str | Path,
    keep_unused: bool = False,
    unused_dir: str | Path = None,
) -> List[Path]:
    """Identify and remove/move calibration files that do not match any raw channel.

    This function finds calibration channels that are not referenced by any
    entry in the mapping (including multiple-match candidates) and either
    deletes or moves the corresponding files.

    Args:
        result: MappingResult from :func:`build_mapping`.
        calibration_data: The calibration data dict returned by
            :func:`load_calibration_data_from_single_files`.
        cal_files_dir: Directory containing the single-channel ``.yml`` files.
        keep_unused: If True, move unused files to *unused_dir* instead of
            deleting them.
        unused_dir: Destination directory for unused files when *keep_unused*
            is True.

    Returns:
        List of Path objects for the unused files that were moved/deleted.
    """
    cal_files_dir = Path(cal_files_dir)
    if unused_dir is not None:
        unused_dir = Path(unused_dir)

    # Collect all cal keys referenced by at least one raw channel
    referenced_keys = set()
    for channels in result.mapping_dict.values():
        referenced_keys.update(channels.values())
    for mm in result.multiple_matches:
        referenced_keys.update(mm.matching_cal_keys)

    # Log unused source (manufacturer) files
    unused_channels = [
        ch for ch in calibration_data.get('channels', [])
        if ch.get('_calibration_file_key') not in referenced_keys
    ]
    if unused_channels:
        ignored_sources = set()
        for ch in unused_channels:
            for src in ch.get('source_filenames', []) or []:
                ignored_sources.add(src)
        if ignored_sources:
            action = "moved to unused folder" if keep_unused else "removed"
            print(f"\n{len(ignored_sources)} manufacturer calibration file(s) "
                  f"not matched by any raw channel ({action}):")
            for src in sorted(ignored_sources):
                print(f"  - {src}")

    # Identify unused standardized calibration files on disk
    referenced_filenames = {
        f"{calibration_key_to_filename(k)}.yml" for k in referenced_keys
    }
    all_cal_files = sorted(cal_files_dir.glob("*.yml"))
    unused_files = [f for f in all_cal_files if f.name not in referenced_filenames]

    for f in unused_files:
        _remove_or_move_file(f, keep_unused, unused_dir)

    if unused_files:
        if keep_unused:
            print(f"\nMoved {len(unused_files)} unused file(s) to: {unused_dir}")
        else:
            print(f"\nDeleted {len(unused_files)} unused file(s).")

    return unused_files


def resolve_conflicts_interactive(
    result: MappingResult,
    cal_files_dir: str | Path,
    keep_unused: bool = False,
    unused_dir: str | Path = None,
) -> None:
    """Interactively resolve multiple-match conflicts by prompting the user.

    When a raw channel matches more than one calibration file, this function
    groups the conflicts, presents the options, and asks the user which file
    to keep. Rejected files are either deleted or moved depending on
    *keep_unused*. The *result* object is modified in-place.

    Args:
        result: MappingResult from :func:`build_mapping` (modified in-place).
        cal_files_dir: Directory containing the single-channel ``.yml`` files.
        keep_unused: If True, move rejected files to *unused_dir*.
        unused_dir: Destination directory for rejected files.
    """
    if not result.multiple_matches:
        return

    cal_files_dir = Path(cal_files_dir)
    if unused_dir is not None:
        unused_dir = Path(unused_dir)

    groups = defaultdict(list)
    for mm in result.multiple_matches:
        key = tuple(sorted(mm.matching_cal_keys))
        groups[key].append(mm)

    print("\n" + "=" * 80)
    print("CONFLICT: MULTIPLE CALIBRATION MATCHES DETECTED")
    print("=" * 80)
    print(f"\n{len(groups)} unique raw configuration(s) matched multiple "
          f"calibration files.")
    print("You will be prompted to choose which file to keep for each conflict.\n")

    keys_to_remove = set()

    for conflict_num, (cal_keys, channels) in enumerate(groups.items(), start=1):
        unique_channel_ids = sorted(set(mm.channel_id for mm in channels))
        options = list(cal_keys)

        print("-" * 60)
        print(f"CONFLICT {conflict_num} of {len(groups)}")
        print("-" * 60)
        print("Affected raw channel(s):")
        for cid in unique_channel_ids:
            print(f"  - {cid}")
        print("\nCalibration file options:")
        for i, cal_key in enumerate(options, start=1):
            cal_data = result.calibration_dict.get(cal_key, {})
            cal_date = cal_data.get('calibration_date', 'unknown')
            src_files = cal_data.get('source_filenames', ['unknown'])
            print(f"  [{i}] {cal_key}.yml")
            print(f"      calibration_date: {cal_date}  |  source: {src_files}")

        while True:
            choice = input(
                f"\n>>> ENTER THE NUMBER OF THE FILE TO KEEP (1-{len(options)}): "
            ).strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                break
            print(f"    INVALID INPUT. PLEASE ENTER A NUMBER BETWEEN 1 AND {len(options)}.")

        keep_idx = int(choice) - 1
        kept_key = options[keep_idx]
        rejected_keys = [k for k in options if k != kept_key]
        keys_to_remove.update(rejected_keys)

        print(f"\n  Keeping: {kept_key}.yml")
        action_word = "Moving" if keep_unused else "Deleting"
        for rk in rejected_keys:
            print(f"  {action_word}: {rk}.yml")

    # Remove/move rejected calibration files from disk
    for cal_key in keys_to_remove:
        fname = f"{calibration_key_to_filename(cal_key)}.yml"
        cal_file = cal_files_dir / fname
        if cal_file.exists():
            _remove_or_move_file(cal_file, keep_unused, unused_dir)

    # Update mapping_dict: replace rejected keys with the kept key
    for filename in result.mapping_dict:
        for channel_id, cal_key in list(result.mapping_dict[filename].items()):
            if cal_key in keys_to_remove:
                for cal_keys_tuple, mms in groups.items():
                    affected_channels = {mm.channel_id for mm in mms}
                    if channel_id in affected_channels:
                        kept = [k for k in cal_keys_tuple if k not in keys_to_remove][0]
                        result.mapping_dict[filename][channel_id] = kept
                        break

    # Remove rejected keys from calibration_dict
    for rk in keys_to_remove:
        result.calibration_dict.pop(rk, None)

    result.multiple_matches.clear()

    print("\n" + "=" * 80)
    print("ALL CONFLICTS RESOLVED")
    print("=" * 80)


def check_for_conflicts(result: MappingResult, cal_files_dir: str | Path = None) -> None:
    """Raise an error if any raw channel matched multiple calibration files.

    Unlike :func:`resolve_conflicts_interactive`, this function does not
    prompt the user. It prints the conflicting files and raises a
    ``ValueError`` so the caller can delete the extras and re-run.

    Args:
        result: MappingResult from :func:`build_mapping`.
        cal_files_dir: Optional path shown in the error message to tell the
            user where to delete files.

    Raises:
        ValueError: If any raw channel has multiple calibration matches.
    """
    if not result.multiple_matches:
        return

    groups = defaultdict(list)
    for mm in result.multiple_matches:
        key = tuple(sorted(mm.matching_cal_keys))
        groups[key].append(mm)

    print("\n" + "=" * 80)
    print("CONFLICT: MULTIPLE CALIBRATION MATCHES DETECTED")
    print("=" * 80)
    print(f"\n{len(groups)} unique raw configuration(s) matched multiple "
          f"calibration files.")
    print("Each raw configuration must match exactly ONE calibration file.")
    if cal_files_dir:
        print(f"Delete the unwanted file(s) from:\n  {cal_files_dir}")
    print("Then re-run this step.\n")

    for cal_keys, channels in groups.items():
        unique_channel_ids = sorted(set(mm.channel_id for mm in channels))
        print("-" * 60)
        print("Conflicting calibration files (keep exactly one):")
        for cal_key in cal_keys:
            cal_data = result.calibration_dict.get(cal_key, {})
            cal_date = cal_data.get('calibration_date', 'unknown')
            src_files = cal_data.get('source_filenames', ['unknown'])
            print(f"  - {cal_key}.yml")
            print(f"    calibration_date: {cal_date}  |  source: {src_files}")
        print(f"\nAffected channel ID(s):")
        for cid in unique_channel_ids:
            print(f"  - {cid}")
        print()

    dir_msg = f" in {cal_files_dir}" if cal_files_dir else ""
    raise ValueError(
        f"Found {len(groups)} unique raw configuration(s) with multiple "
        f"calibration matches{dir_msg}. "
        f"Delete the extras and re-run this step."
    )


def check_required_calibration_params(
    calibration_dict: Dict[str, Dict[str, Any]],
    required_params: List[str] = None,
    environmental_direct: List[str] = None,
    environmental_derived: List[str] = None,
) -> Dict[str, List[str]]:
    """Check that required calibration parameters are present for every channel.

    Args:
        calibration_dict: Maps calibration key -> calibration data dict.
        required_params: List of required parameter names. Defaults to
            :data:`REQUIRED_CALIBRATION_PARAMS`.
        environmental_direct: Direct environmental parameter names. Defaults
            to :data:`ENVIRONMENTAL_DIRECT`.
        environmental_derived: Derived environmental parameter names. Defaults
            to :data:`ENVIRONMENTAL_DERIVED`.

    Returns:
        Dictionary mapping calibration key -> list of missing parameter
        descriptions. An empty dict means all parameters are present.
    """
    if required_params is None:
        required_params = REQUIRED_CALIBRATION_PARAMS
    if environmental_direct is None:
        environmental_direct = ENVIRONMENTAL_DIRECT
    if environmental_derived is None:
        environmental_derived = ENVIRONMENTAL_DERIVED

    print("=" * 80)
    print("MISSING REQUIRED CALIBRATION PARAMETER CHECK")
    print("=" * 80)

    missing_by_key: Dict[str, List[str]] = {}

    for cal_key, cal_data in calibration_dict.items():
        missing = []

        for param in required_params:
            if _is_missing(cal_data.get(param)):
                missing.append(param)

        missing_direct = [p for p in environmental_direct if _is_missing(cal_data.get(p))]
        missing_derived = [p for p in environmental_derived if _is_missing(cal_data.get(p))]

        if missing_direct and missing_derived:
            missing.extend(
                [f"{p}  (or provide {', '.join(environmental_derived)})" for p in missing_direct]
            )

        if missing:
            missing_by_key[cal_key] = missing
            print(f"\n  Calibration key: {cal_key}")
            for param in missing:
                print(f"     - MISSING REQUIRED: {param}")

    if not missing_by_key:
        print("\n All required calibration parameters are present for every mapped channel.")

    return missing_by_key


def verify_calibration_file_usage(
    calibration_dict: Dict[str, Dict[str, Any]],
    cal_files_dir: str | Path,
) -> List[Path]:
    """Verify that every calibration file in a directory is used in the mapping.

    Args:
        calibration_dict: Maps calibration key -> calibration data dict
            (the keys currently in use).
        cal_files_dir: Directory containing single-channel ``.yml`` files.

    Returns:
        List of unused file Paths. An empty list means all files are used.
    """
    cal_files_dir = Path(cal_files_dir)
    used_filenames = {
        f"{calibration_key_to_filename(k)}.yml" for k in calibration_dict
    }
    all_cal_files = sorted(cal_files_dir.glob("*.yml"))
    unused_files = [f for f in all_cal_files if f.name not in used_filenames]

    print("=" * 80)
    print("CALIBRATION FILE USAGE CHECK")
    print("=" * 80)

    if unused_files:
        print(f"\n  {len(unused_files)} single-channel calibration file(s) are NOT used in the mapping:")
        for f in unused_files:
            print(f"     - {f.name}")
        print(f"\n   Re-run the mapping step to resolve these.")
    else:
        print("\n All single-channel calibration files are used in the mapping.")

    return unused_files


def set_record_author(calibration_data: Dict[str, Any], record_author: str) -> None:
    """Set record_author on calibration channels where it is not already set.

    Args:
        calibration_data: Calibration data dict with a ``'channels'`` key.
        record_author: Author name to set.
    """
    for ch in calibration_data.get('channels', []):
        if ch.get('record_author') is None:
            ch['record_author'] = record_author
