"""
Calibration Library Package

This package provides tools for managing calibration data for acoustic instruments.

Modules:
    - mapping_algorithm: Match raw file configurations to calibration data
    - calibration: Additional calibration utilities
    - raw_reader_api: Raw file reading interface
    - standardized_file_lib: Standardized calibration file I/O and schema validation
    - manufacturer_file_parsers: Parse EK60/EK80 manufacturer calibration files
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("calibration_library")
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
)

from .standardized_file_lib import (
    calibration_key_to_filename,
    build_short_filename_map,
    remap_to_short_keys,
    print_short_key_summary,
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
]
