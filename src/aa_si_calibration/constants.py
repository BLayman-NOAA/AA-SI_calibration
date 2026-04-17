"""Shared constants for the calibration library."""

from pathlib import Path
import re


# Path to the JSON schema for standardized calibration files
SCHEMA_PATH = Path(__file__).parent / "schema" / "standardized_calibration_file_schema.json"

# Regex matching hex-like serial number substrings (10-16 hex chars)
SERIAL_NUMBER_PATTERN = re.compile(r"\b[0-9A-Fa-f]{10,16}\b")

# Regex extracting the nominal CW frequency (kHz) from transducer model names
# e.g. "ES38-7" -> group(1) = "38", "ES120-7C" -> group(1) = "120"
NOMINAL_FREQ_PATTERN = re.compile(r'^[A-Za-z]+(\d+)')

# Fields that should always be stored as strings in YAML output for consistency
STRING_IDENTIFIER_FIELDS = [
    'transceiver_id',
    'transceiver_ethernet_address',
    'transceiver_serial_number',
    'transducer_serial_number',
]

# Pulse form identifiers used in raw file configurations
PULSE_FORM_CW = "0"
PULSE_FORM_FM = "1"

# Placeholder for unknown transducer serial numbers
TRANSDUCER_SERIAL_UNKNOWN = "NoSN"

# Calibration flags file
FLAGS_FILENAME = "calibration_flags.json"
FLAG_CATEGORIES = [
    "moderate_impacts",
    "large_impacts",
    "critical_impacts",
    "data_irregularities",
    "missing_parameters",
]
