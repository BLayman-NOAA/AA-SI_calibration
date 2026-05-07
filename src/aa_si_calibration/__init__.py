"""Calibration library for managing acoustic instrument calibration data."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aa-si-calibration")
except PackageNotFoundError:
    # Package is not installed (e.g., running from source without install)
    __version__ = "0.0.0.dev"

from .mapping_algorithm import (
    # Data classes
    MappingResult,
    UnmatchedChannel,
    MultipleMatchChannel,
    MultiplexingWarning,
    
    # Configuration
    DEFAULT_TOLERANCES,
    REQUIRED_CALIBRATION_PARAMS,
    ENVIRONMENTAL_DIRECT,
    ENVIRONMENTAL_DERIVED,
    
    # Helper functions
    values_match_with_tolerance,
    frequency_range_is_valid,
    strings_match,
    check_multiplexing,
    find_matching_calibration,
    build_calibration_key,
    
    # Main functions
    load_raw_configs,
    load_calibration_data,
    load_calibration_data_from_single_files,
    build_mapping,
    get_calibration,
    get_calibration_from_file,
    
    # Output functions
    save_mapping_files,
    save_individual_calibration_files,
    print_mapping_preview,
    
    # High-level pipeline functions
    handle_unused_calibration_files,
    resolve_conflicts_interactive,
    check_for_conflicts,
    check_required_calibration_params,
    verify_calibration_file_usage,
    set_record_author,
)

from .standardized_file_lib import (
    calibration_key_to_filename,
    build_short_filename_map,
    remap_to_short_keys,
    print_short_key_summary,
    generate_calibration_templates,
    validate_loaded_templates,
    load_calibration_templates,
    save_multi_channel_config_with_comments,
    check_required_fields,
)

__all__ = [
    '__version__',
    
    # Data classes
    'MappingResult',
    'UnmatchedChannel',
    'MultipleMatchChannel',
    'MultiplexingWarning',
    
    # Configuration
    'DEFAULT_TOLERANCES',
    'REQUIRED_CALIBRATION_PARAMS',
    'ENVIRONMENTAL_DIRECT',
    'ENVIRONMENTAL_DERIVED',
    
    # Helper functions
    'values_match_with_tolerance',
    'frequency_range_is_valid',
    'strings_match',
    'check_multiplexing',
    'find_matching_calibration',
    'build_calibration_key',
    'calibration_key_to_filename',
    'build_short_filename_map',
    'remap_to_short_keys',
    'print_short_key_summary',
    
    # Main functions
    'load_raw_configs',
    'load_calibration_data',
    'load_calibration_data_from_single_files',
    'build_mapping',
    'get_calibration',
    'get_calibration_from_file',
    
    # Output functions
    'save_mapping_files',
    'save_individual_calibration_files',
    'print_mapping_preview',
    
    # High-level pipeline functions
    'handle_unused_calibration_files',
    'resolve_conflicts_interactive',
    'check_for_conflicts',
    'check_required_calibration_params',
    'verify_calibration_file_usage',
    'set_record_author',
    'generate_calibration_templates',
    'validate_loaded_templates',
    'load_calibration_templates',
    'save_multi_channel_config_with_comments',
    'check_required_fields',
]
