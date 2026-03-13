"""Shared utility functions for the calibration library."""

from .constants import NOMINAL_FREQ_PATTERN


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
