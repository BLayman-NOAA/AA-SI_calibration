"""Shared utility functions for the calibration library."""

import json
import os
from pathlib import Path

from .constants import NOMINAL_FREQ_PATTERN, FLAGS_FILENAME, FLAG_CATEGORIES


def extract_nominal_frequency_from_transducer_model(transducer_model):
    """Extract the nominal CW operating frequency (Hz) from a transducer model name.
    
    Simrad transducer model names embed the nominal frequency in kHz after
    the alphabetic prefix.  Examples:
    
    - ES38-7     -> 38000 Hz
    - ES38B      -> 38000 Hz
    - ES120-7C   -> 120000 Hz
    - Combi200   -> 200000 Hz
    - ES18       -> 18000 Hz
    - ES18-11    -> 18000 Hz
    
    Args:
        transducer_model: Transducer model string (e.g., "ES38-7").
    
    Returns:
        Nominal frequency in Hz (int), or None if extraction fails.
    """
    if transducer_model is None:
        return None
    model_str = transducer_model if isinstance(transducer_model, str) else str(transducer_model)
    match = NOMINAL_FREQ_PATTERN.search(model_str)
    if match:
        try:
            return int(match.group(1)) * 1000
        except (ValueError, TypeError):
            return None
    return None


class CalibrationFlags:
    """Manages calibration flags stored as JSON.

    Handles loading, updating, and saving the calibration_flags.json file
    that tracks missing parameters, data irregularities, and impact levels.

    Args:
        output_logs_folder: Path to the folder containing the flags file.

    Example::

        flags = CalibrationFlags(output_logs_folder)
        flags.add("missing_parameters", "Environment/sound_speed_indicative")
        flags.save()
    """

    def __init__(self, output_logs_folder):
        os.makedirs(output_logs_folder, exist_ok=True)
        self._path = Path(output_logs_folder) / FLAGS_FILENAME
        if self._path.exists():
            with open(self._path, 'r') as f:
                self._data = json.load(f)
        else:
            self._data = {cat: [] for cat in FLAG_CATEGORIES}
        for cat in FLAG_CATEGORIES:
            self._data.setdefault(cat, [])

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def add(self, category, entry):
        """Append an entry to a flag category.

        Args:
            category: One of the flag category keys (e.g. "missing_parameters").
            entry: The value to append (string or dict).
        """
        self._data[category].append(entry)

    def save(self):
        """Write the current flags to disk."""
        with open(self._path, 'w') as f:
            json.dump(self._data, f, indent=2)
