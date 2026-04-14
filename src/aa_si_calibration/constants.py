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
