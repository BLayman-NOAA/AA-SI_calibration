# imports and variables
from pathlib import Path
import json
import re

from .utils import extract_nominal_frequency_from_transducer_model



def extract_calibration_params_from_EK60_report(cal_folder, nc_frequencies, output_logs_folder):
    """Extract calibration parameters from EK60 .cal files.
    
    Parses EK60 calibration files (.cal) to extract various calibration parameters
    including transducer parameters, environmental conditions, and beam model results.
    The extracted data is organized by frequency and sorted to match the provided
    frequency ordering from the netCDF file.
    
    Args:
        cal_folder (Path): Path to folder containing .cal files
        nc_frequencies: Array of frequencies from netCDF file for sorting order
        output_logs_folder: Path to folder for saving log files
        
    Returns:
        dict: Dictionary with parameter names as keys and lists of values for each frequency.
              Keys include: 'frequency', 'Two Way Beam Angle', 'Absorption Coeff.',
              'Sound Velocity', 'SaCorrection', 'Transducer Gain', 'source_filenames', etc.
    """
    
    cal_files = list(cal_folder.glob('*.cal'))
    print(f"Found {len(cal_files)} calibration files in {cal_folder}")
    cal_data_by_freq = {}

    if cal_files:
        # Parse all calibration files to extract parameters for each frequency
        for cal_file in cal_files:
            print(f"\nParsing: {cal_file.name}")
            
            try:
                with open(cal_file, 'r') as f:
                    cal_content = f.read()
                
                # Extract calibration parameters using the actual .cal file format
                cal_params = {}
                cal_params['source_filenames'] = cal_file.name
                lines = cal_content.split('\n')
                
                # State tracking for different sections
                in_transducer_section = False
                in_environment_section = False
                in_beam_model_section = False
                in_sounder_type_section = False
                in_transceiver_section = False
                
                for i in range(len(lines)):
                    line = lines[i]

                    line = line.strip()
                    
                    # Skip empty lines and lines without # (data section)
                    if not line or not line.startswith('#'):
                        continue
                    
                    # Remove the # and extra spaces
                    line_content = line[1:].strip()
                    
                    # Extract Date from header (appears near top before sections)
                    if line_content.startswith('Date:'):
                        try:
                            parts = line_content.split()
                            cal_params['Date'] = parts[1]
                        except:
                            pass
                        continue
                    
                    # Extract Comments from header (appears near top before sections)
                    if line_content.startswith('Comments:'):
                        try:
                            cal_params['Comments'] = lines[i+1][1:]
                        except:
                            pass
                        continue
                    
                    # Identify sections
                    if line_content.startswith('Transducer:'):
                        in_transducer_section = True
                        in_environment_section = False
                        in_beam_model_section = False
                        in_sounder_type_section = False
                        in_transceiver_section = False
                        # Extract transducer info from the section header
                        try:
                            transducer_info = line_content.replace('Transducer:', '').strip()
                            cal_params['Transducer'] = transducer_info
                        except:
                            pass
                        continue
                    elif line_content.startswith('Environment:'):
                        in_transducer_section = False
                        in_environment_section = True
                        in_beam_model_section = False
                        in_sounder_type_section = False
                        in_transceiver_section = False
                        continue
                    elif line_content.startswith('Beam Model results:'):
                        in_transducer_section = False
                        in_environment_section = False
                        in_beam_model_section = True
                        in_sounder_type_section = False
                        in_transceiver_section = False
                        continue
                    elif line_content.startswith('Sounder Type:'):
                        in_transducer_section = False
                        in_environment_section = False
                        in_beam_model_section = False
                        in_sounder_type_section = True
                        in_transceiver_section = False
                        continue
                    elif line_content.startswith('Transceiver:'):
                        in_transducer_section = False
                        in_environment_section = False
                        in_beam_model_section = False
                        in_sounder_type_section = False
                        in_transceiver_section = True
                        # Extract transceiver info from the section header
                        try:
                            transceiver_info = line_content.replace('Transceiver:', '').strip()
                            cal_params['Transceiver'] = transceiver_info
                        except:
                            pass
                        continue
                    elif (line_content.startswith('Data deviation') or 
                            line_content.startswith('TS Detection:')):
                        # These sections end all parsing
                        in_transducer_section = False
                        in_environment_section = False
                        in_beam_model_section = False
                        in_sounder_type_section = False
                        in_transceiver_section = False
                        continue
                    
                    # Parse transducer section parameters
                    if in_transducer_section:
                        try:
                            if 'Frequency' in line_content and 'Hz' in line_content:
                                parts = line_content.split()
                                if 'Frequency' in parts:
                                    freq_idx = parts.index('Frequency') + 1
                                    if freq_idx < len(parts):
                                        freq = float(parts[freq_idx])
                                        cal_params['frequency'] = freq
                            # equivalent_beam_angle, and transducer_gain_correction
                            elif 'Two Way Beam Angle' in line_content and 'dB' in line_content:
                                parts = line_content.split()
                                for j in range(len(parts)-3):
                                    if (parts[j] == 'Two' and parts[j+1] == 'Way' and 
                                        parts[j+2] == 'Beam' and parts[j+3] == 'Angle'):
                                        if j+4 < len(parts):
                                            twba = float(parts[j+4])
                                            cal_params['Two Way Beam Angle'] = twba
                                        break
                            # Extract Athw. Angle Sens.
                            elif 'Athw. Angle Sens.' in line_content:
                                parts = line_content.split()
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Athw.' and parts[j+1] == 'Angle' and parts[j+2] == 'Sens.'):
                                        if j+3 < len(parts):
                                            athw_sens = float(parts[j+3])
                                            cal_params['Athw. Angle Sens.'] = athw_sens
                                parts = line_content.split()
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Along.' and parts[j+1] == 'Angle' and parts[j+2] == 'Sens.'):
                                        if j+3 < len(parts):
                                            along_sens = float(parts[j+3])
                                            cal_params['Along. Angle Sens.'] = along_sens
                                        break
                                
                            # Extract transducer name (with serial number)
                            elif 'Transducer Name' in line_content:
                                parts = line_content.split()
                                if len(parts) > 3:
                                    # Join all but last part as name, last part as serial number
                                    transducer_name = ' '.join(parts[:-1])
                                    transducer_serial = parts[-1]
                                    cal_params['Transducer Name'] = transducer_name
                                    cal_params['Transducer Serial'] = transducer_serial
                                
                        except ValueError:
                            # Skip problematic lines without printing errors for expected format variations
                            pass
                        except Exception as e:
                            print(f"      Unexpected error in transducer section: {e}")
                    
                    # Parse transceiver section parameters
                    elif in_transceiver_section:
                        try:
                            # Extract Sample Interval
                            if 'Sample Interval' in line_content:
                                parts = line_content.split()
                                for j in range(len(parts)-1):
                                    if (parts[j] == 'Sample' and parts[j+1] == 'Interval'):
                                        if j+2 < len(parts):
                                            sample_interval = float(parts[j+2])
                                            cal_params['Sample Interval'] = sample_interval
                                    if (parts[j] == 'Pulse' and parts[j+1] == 'Duration'):
                                        if j+2 < len(parts):
                                            pulse_duration = float(parts[j+2])
                                            cal_params['Pulse Duration'] = pulse_duration

                            # Extract Power
                            elif 'Power' in line_content and 'W' in line_content:
                                parts = line_content.split()
                                if 'Power' in parts:
                                    power_idx = parts.index('Power') + 1
                                    if power_idx < len(parts):
                                        power = float(parts[power_idx])
                                        cal_params['Power'] = power
                                if 'Receiver' in parts:
                                    bandw_idx = parts.index('Receiver') + 2
                                    if bandw_idx < len(parts):
                                        bandw = float(parts[bandw_idx])
                                        cal_params['Receiver Bandwidth'] = bandw
                        except ValueError:
                            pass
                        except Exception as e:
                            print(f"      Unexpected error in transceiver section: {e}")
                    
                    # Parse sounder type section
                    elif in_sounder_type_section:
                        try:
                            # Extract EK60 Version
                            if 'EK60 Version' in line_content:
                                parts = line_content.split()
                                if 'Version' in parts:
                                    version_idx = parts.index('Version') + 1
                                    if version_idx < len(parts):
                                        version = parts[version_idx]
                                        cal_params['Sounder Type Version'] = version
                        except Exception as e:
                            print(f"      Unexpected error in sounder type section: {e}")
                    
                    # Parse environment section parameters
                    elif in_environment_section:
                        try:
                            # Handle case where both absorption and sound velocity are on the same line
                            # Format: "#    Absorption Coeff.   2.3 dB/km       Sound Velocity     1498.3 m/s"
                            if 'Absorption Coeff.' in line_content and 'Sound Velocity' in line_content:
                                parts = line_content.split()
                                
                                # Extract absorption coefficient
                                if 'Absorption' in parts and 'Coeff.' in parts:
                                    abs_idx = parts.index('Coeff.') + 1
                                    if abs_idx < len(parts):
                                        absorption = float(parts[abs_idx])
                                        cal_params['Absorption Coeff.'] = absorption # dB/km
                                
                                # Extract sound velocity
                                if 'Sound' in parts and 'Velocity' in parts:
                                    sound_idx = parts.index('Velocity') + 1
                                    if sound_idx < len(parts):
                                        sound_speed_num = float(parts[sound_idx])
                                        cal_params['Sound Velocity'] = sound_speed_num
                            
                                        
                        except ValueError:
                            # Skip problematic lines
                            pass
                        except Exception as e:
                            print(f"      Unexpected error in environment section: {e}")
                    
                    # Parse beam model results (final calibrated values)
                    elif in_beam_model_section:
                        try:
                            # Handle "=" with or without spaces by replacing with space first
                            line_content_normalized = line_content.replace("=", " ")
                            
                            if 'Transducer Gain' in line_content_normalized:
                                parts = line_content_normalized.split()
                                if len(parts) > 1:
                                    if 'SaCorrection' in parts:
                                        sa_idx = parts.index('SaCorrection') + 1
                                        if sa_idx < len(parts):
                                            sa_corr = float(parts[sa_idx])
                                            cal_params['SaCorrection'] = sa_corr
                                    if 'Gain' in parts:
                                        idx = parts.index('Gain') + 1
                                        if idx < len(parts):
                                            beam_gain = float(parts[idx])
                                            cal_params['Transducer Gain'] = beam_gain
                                    

                            elif 'Athw. Beam Angle' in line_content_normalized:
                                parts = line_content_normalized.split()
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Athw.' and parts[j+1] == 'Beam' and parts[j+2] == 'Angle'):
                                        if j+3 < len(parts):
                                            athw_angle = float(parts[j+3])
                                            cal_params['Athw. Beam Angle'] = athw_angle
                                        break
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Along.' and parts[j+1] == 'Beam' and parts[j+2] == 'Angle'):
                                        if j+3 < len(parts):
                                            along_angle = float(parts[j+3])
                                            cal_params['Along. Beam Angle'] = along_angle
                                        break
                            # Extract Athw. Offset Angle from Beam Model results
                            elif 'Athw. Offset Angle' in line_content_normalized:
                                parts = line_content_normalized.split()
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Athw.' and parts[j+1] == 'Offset' and parts[j+2] == 'Angle'):
                                        if j+3 < len(parts):
                                            athw_offset = float(parts[j+3])
                                            cal_params['Athw. Offset Angle'] = athw_offset
                                        break
                                # Also check for Along. Offset Angle on same line
                                for j in range(len(parts)-2):
                                    if (parts[j] == 'Along.' and parts[j+1] == 'Offset' and parts[j+2] == 'Angle'):
                                        if j+3 < len(parts):
                                            along_offset = float(parts[j+3])
                                            cal_params['Along. Offset Angle'] = along_offset
                                        break
                                    
                        except ValueError:
                            # Skip problematic lines
                            pass
                        except Exception as e:
                            print(f"      Unexpected error in beam model section: {e}")
                
                # Store calibration data by frequency
                if 'frequency' in cal_params:
                    freq_key = f"{cal_params['frequency']/1000:.0f}kHz"
                    cal_data_by_freq[freq_key] = cal_params
                    print(f"   Extracted parameters for {freq_key}")
                    
                else:
                    print(f"   Could not extract frequency from {cal_file.name}")
                
            except Exception as e:
                print(f"   Error parsing {cal_file.name}: {e}")

                
        
        print(f"\nSuccessfully parsed calibration data for {len(cal_data_by_freq)} frequencies:")

        cal_data_list = [] # list of object with one object for each frequency
        # for each frequency
        for freq_key in cal_data_by_freq.keys():
            # append dictionary of calibration data
            cal_data_list.append(cal_data_by_freq[freq_key])
            print(f"   • {freq_key}")
            # for each set of calibration parameters in that dictionary, print items
            for param, value in cal_data_by_freq[freq_key].items():
                if 'Gain' in param or 'Correction' in param or 'Two Way' in param:
                    print(f"      {param}: {value:.2f} dB")
                elif 'Absorption' in param:
                    print(f"      {param}: {value:.1f} dB/km")
                elif 'Velocity' in param:
                    print(f"      {param}: {value:.1f} m/s")
                elif 'Athw' in param or "Along" in param:
                    print(f"      {param}: {value:.2f} deg")
                elif 'Sample Interval' in param:
                    print(f"      {param}: {value:.3f} m")
                elif 'frequency' in param:
                    print(f"      {param}: {value:.0f} Hz")
                elif 'Receiver Bandwidth' in param:
                    print(f"      {param}: {value:.2f} kHz")
                elif 'Power' in param:
                    print(f"      {param}: {value:.0f} W")
                elif param in ['Transceiver', 'Transducer', 'Date', 'Comments', 'Sounder Type Version', 'source_filenames']:
                    print(f"      {param}: {value}")
                else:
                    print(f"      {param}: {value:.0f}")

        # sorted_cal_data_list = sorted(cal_data_list, key=lambda cal_params: cal_params['frequency'])

        # Sort by provided frequencies instead of ascending order
        # Create a mapping from each frequency to its index (its sort position)
        freq_to_index_map = {freq: i for i, freq in enumerate(nc_frequencies)}

        # Use this map to sort the list. Dictionary lookups are very fast.
        sorted_cal_data_list = sorted(cal_data_list, key=lambda p: freq_to_index_map[p['frequency']])
        
        # Collect all keys across all frequencies so that missing keys
        # are padded with None (prevents list-length misalignment).
        all_keys = {}
        for params in sorted_cal_data_list:
            for key in params:
                all_keys[key] = None  # insertion-ordered dict preserves key order

        cal_data_refactored = {key: [] for key in all_keys}
        for params in sorted_cal_data_list:
            for key in all_keys:
                cal_data_refactored[key].append(params.get(key))



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
    
    # Ensure all required keys exist
    for key in ["moderate_impacts", "large_impacts", "critical_impacts", "data_irregularities", "missing_parameters"]:
        flags.setdefault(key, [])


    # Check for missing parameters and add entries to calibration_flags.json "missing_parameters"
    if len(cal_data_by_freq) > 0:  # Only check if we found calibration params
        expected_parameters = [
            "Two Way Beam Angle",
            "Transducer Gain", 
            "SaCorrection",
            "Athw. Beam Angle",
            "Along. Beam Angle",
            "Athw. Offset Angle", 
            "Along. Offset Angle",
            "Athw. Angle Sens.",
            "Along. Angle Sens.",
            "Sound Velocity",
            "Absorption Coeff.",
            "frequency",
            "Sounder Type Version",
            "Transceiver",
            "Power", 
            "Pulse Duration",
            "Receiver Bandwidth",
            "Sample Interval",
            "Transducer",
            "Date",
            "Comments",
            "source_filenames"
        ]
        
        missing_params = []
        for param in expected_parameters:
            if param not in cal_data_refactored or cal_data_refactored[param] is None:
                missing_params.append(param)
        
        # Log missing parameters
        for param in missing_params:
            flags["missing_parameters"].append(f"Missing EK60 report parameter: {param}")
            print(f"Warning: Missing EK60 report parameter: {param}")
        
        if missing_params:
            print(f"\nTotal missing EK60 report parameters: {len(missing_params)}")
        else:
            print(f"\nAll expected EK60 report parameters found successfully")
    else:
        # No calibration files found
        flags["missing_parameters"].append("No EK60 calibration files (.cal) found in specified folder")
        print("Warning: No EK60 calibration files (.cal) found in specified folder")
    
    # Save updated flags to JSON
    with open(flags_file, 'w') as f:
        json.dump(flags, f, indent=2)

    return cal_data_refactored



def extract_calibration_params_from_EK80_xml(cal_folder, output_logs_folder=None):
    """Extract calibration parameters from EK80 XML calibration files.
    
    Parses EK80 XML calibration files to extract calibration parameters including
    frequency-dependent arrays for FM/broadband mode. Each XML file corresponds to
    one channel/transducer configuration.
    
    Args:
        cal_folder (Path): Path to folder containing EK80 XML calibration files
        output_logs_folder (Path, optional): Path to folder for saving log files.
            If None, logging to file is skipped.
        
    Returns:
        dict: Dictionary with parameter names matching EK80 XML element names as
              keys. For FM mode, calibration result parameters (Gain, SaCorrection,
              BeamWidthAlongship, BeamWidthAthwartship, AngleOffsetAlongship,
              AngleOffsetAthwartship) are arrays across the frequency sweep.
              Use convert_ek80_params_to_pipeline_format() to map these to
              the echopype/pipeline naming convention.
              
    Note:
        Unlike EK60 which has one .cal file per frequency, EK80 has one XML file
        per channel. Each file may contain arrays of values across the FM frequency
        range within CalibrationResults.
    """
    import xml.etree.ElementTree as ET
    from datetime import datetime
    
    cal_folder = Path(cal_folder)
    
    # Find all EK80 XML calibration files
    xml_files = list(cal_folder.glob('*.xml'))
    print(f"Found {len(xml_files)} EK80 XML calibration files in {cal_folder}")
    
    cal_data_by_channel = {}
    
    if not xml_files:
        print("Warning: No EK80 XML calibration files found")
        # Handle logging if output folder provided
        if output_logs_folder:
            _log_ek80_missing_params(output_logs_folder, [], is_empty=True)
        return {}
    
    for xml_file in xml_files:
        print(f"\nParsing: {xml_file.name}")
        
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            cal_params = {}
            cal_params['source_filenames'] = xml_file.name
            
            # Find the Calibration element
            calibration = root.find('.//Calibration')
            if calibration is None:
                print(f"   Warning: No Calibration element found in {xml_file.name}")
                continue
            
            # === Extract Common section parameters ===
            common = calibration.find('Common')
            if common is not None:
                # Time of file creation (calibration date)
                time_elem = common.find('TimeOfFileCreation')
                if time_elem is not None and time_elem.text:
                    try:
                        # Parse ISO format datetime, extract date portion
                        dt_str = time_elem.text.split('T')[0]
                        cal_params['Date'] = dt_str
                    except:
                        cal_params['Date'] = time_elem.text
                
                # Transducer info
                transducer = common.find('Transducer')
                if transducer is not None:
                    name_elem = transducer.find('Name')
                    if name_elem is not None and name_elem.text:
                        cal_params['Transducer'] = name_elem.text
                    
                    serial_elem = transducer.find('SerialNumber')
                    if serial_elem is not None and serial_elem.text and serial_elem.text.strip() != '0':
                        cal_params['Transducer Serial'] = serial_elem.text
                    else:
                        # Treat missing or '0' serial as null (not a real serial number)
                        cal_params['Transducer Serial'] = None
                    
                    depth_elem = transducer.find('TransducerDepth')
                    if depth_elem is not None and depth_elem.text:
                        cal_params['Transducer Depth'] = float(depth_elem.text)
                
                # Transceiver info
                transceiver = common.find('Transceiver')
                if transceiver is not None:
                    channel_elem = transceiver.find('ChannelName')
                    if channel_elem is not None and channel_elem.text:
                        cal_params['Channel Name'] = channel_elem.text
                    
                    serial_elem = transceiver.find('SerialNumber')
                    if serial_elem is not None and serial_elem.text:
                        cal_params['Transceiver Serial'] = serial_elem.text
                    
                    type_elem = transceiver.find('Type')
                    if type_elem is not None and type_elem.text:
                        cal_params['Transceiver Type'] = type_elem.text
                    
                    impedance_elem = transceiver.find('Impedance')
                    if impedance_elem is not None and impedance_elem.text:
                        cal_params['Transceiver Impedance'] = float(impedance_elem.text)
                
                # Application/Software info
                application = common.find('Application')
                if application is not None:
                    name_elem = application.find('Name')
                    if name_elem is not None and name_elem.text:
                        cal_params['Sonar Software Name'] = name_elem.text
                    
                    version_elem = application.find('SoftwareVersion')
                    if version_elem is not None and version_elem.text:
                        cal_params['SoftwareVersion'] = version_elem.text
                
                # TransceiverSetting - operational parameters
                transceiver_setting = common.find('TransceiverSetting')
                if transceiver_setting is not None:
                    beam_type_elem = transceiver_setting.find('BeamType')
                    if beam_type_elem is not None and beam_type_elem.text:
                        cal_params['Beam Type'] = beam_type_elem.text
                    
                    freq_start_elem = transceiver_setting.find('FrequencyStart')
                    if freq_start_elem is not None and freq_start_elem.text:
                        cal_params['Frequency Start'] = float(freq_start_elem.text)
                    
                    freq_end_elem = transceiver_setting.find('FrequencyEnd')
                    if freq_end_elem is not None and freq_end_elem.text:
                        cal_params['Frequency End'] = float(freq_end_elem.text)
                    
                    pulse_length_elem = transceiver_setting.find('PulseLength')
                    if pulse_length_elem is not None and pulse_length_elem.text:
                        # Already in seconds
                        cal_params['PulseLength'] = float(pulse_length_elem.text)
                    
                    pulse_form_elem = transceiver_setting.find('PulseForm')
                    if pulse_form_elem is not None and pulse_form_elem.text:
                        # LFM = FM mode, CW = continuous wave
                        pulse_form = pulse_form_elem.text
                        cal_params['Pulse Form'] = pulse_form
                        # Map to numeric: 0=CW, 1=FM
                        if pulse_form.upper() in ['LFM', 'FM']:
                            cal_params['Pulse Form Code'] = 1
                        else:
                            cal_params['Pulse Form Code'] = 0
                    
                    power_elem = transceiver_setting.find('TransmitPower')
                    if power_elem is not None and power_elem.text:
                        cal_params['TransmitPower'] = float(power_elem.text)
                    
                    sample_interval_elem = transceiver_setting.find('SampleInterval')
                    if sample_interval_elem is not None and sample_interval_elem.text:
                        # Already in seconds
                        cal_params['SampleInterval'] = float(sample_interval_elem.text)
                
                # EnvironmentData
                env_data = common.find('EnvironmentData')
                if env_data is not None:
                    sound_vel_elem = env_data.find('SoundVelocity')
                    if sound_vel_elem is not None and sound_vel_elem.text:
                        cal_params['SoundVelocity'] = float(sound_vel_elem.text)
                    
                    absorption_elem = env_data.find('AbsorptionCoefficient')
                    if absorption_elem is not None and absorption_elem.text:
                        # EK80 stores absorption in dB/m - keep native unit
                        cal_params['AbsorptionCoefficient'] = float(absorption_elem.text)
                    
                    temp_elem = env_data.find('Temperature')
                    if temp_elem is not None and temp_elem.text:
                        cal_params['Temperature'] = float(temp_elem.text)
                    
                    salinity_elem = env_data.find('Salinity')
                    if salinity_elem is not None and salinity_elem.text:
                        cal_params['Salinity'] = float(salinity_elem.text)
                    
                    acidity_elem = env_data.find('Acidity')
                    if acidity_elem is not None and acidity_elem.text:
                        cal_params['pH'] = float(acidity_elem.text)
                
                # PreviousModelParameters - may contain EquivalentBeamAngle
                prev_model = common.find('PreviousModelParameters')
                if prev_model is not None:
                    eba_elem = prev_model.find('EquivalentBeamAngle')
                    if eba_elem is not None and eba_elem.text:
                        cal_params['EquivalentBeamAngle'] = float(eba_elem.text)
            
            # === Extract TargetReference (calibration sphere) ===
            target_ref = calibration.find('TargetReference')
            if target_ref is not None:
                sphere_name_elem = target_ref.find('Name')
                if sphere_name_elem is not None and sphere_name_elem.text:
                    cal_params['Sphere Name'] = sphere_name_elem.text
                    # Parse material from name (e.g., "Tungsten (WC-Co) 38.1mm")
                    name_lower = sphere_name_elem.text.lower()
                    if 'tungsten' in name_lower or 'wc' in name_lower:
                        cal_params['Sphere Material'] = 'tungsten carbide'
                    elif 'copper' in name_lower or 'cu' in name_lower:
                        cal_params['Sphere Material'] = 'copper'
                
                diameter_elem = target_ref.find('Diameter')
                if diameter_elem is not None and diameter_elem.text:
                    cal_params['Sphere Diameter'] = float(diameter_elem.text)
            
            # === Extract CalibrationResults (frequency-dependent arrays for FM) ===
            cal_results = calibration.find('CalibrationResults')
            if cal_results is not None:
                # Parse semicolon-separated arrays
                def parse_array(element_name):
                    elem = cal_results.find(element_name)
                    if elem is not None and elem.text:
                        try:
                            values = [float(v) for v in elem.text.split(';') if v.strip()]
                            return values
                        except ValueError:
                            return None
                    return None
                
                # Frequency array (Hz)
                freq_array = parse_array('Frequency')
                if freq_array:
                    cal_params['frequency'] = freq_array
                
                # Gain array (dB) - this is the transducer gain correction
                gain_array = parse_array('Gain')
                if gain_array:
                    cal_params['Gain'] = gain_array
                
                # SaCorrection array (dB)
                sa_array = parse_array('SaCorrection')
                if sa_array:
                    cal_params['SaCorrection'] = sa_array
                
                # BeamWidth arrays (degrees)
                bw_along_array = parse_array('BeamWidthAlongship')
                if bw_along_array:
                    cal_params['BeamWidthAlongship'] = bw_along_array
                
                bw_athw_array = parse_array('BeamWidthAthwartship')
                if bw_athw_array:
                    cal_params['BeamWidthAthwartship'] = bw_athw_array
                
                # AngleOffset arrays (degrees)
                offset_along_array = parse_array('AngleOffsetAlongship')
                if offset_along_array:
                    cal_params['AngleOffsetAlongship'] = offset_along_array
                
                offset_athw_array = parse_array('AngleOffsetAthwartship')
                if offset_athw_array:
                    cal_params['AngleOffsetAthwartship'] = offset_athw_array
                
                # TsRmsError array (for quality assessment)
                ts_rms_array = parse_array('TsRmsError')
                if ts_rms_array:
                    cal_params['TsRmsError'] = ts_rms_array
            
            # === Extract Description (comments) ===
            desc_elem = calibration.find('Description')
            if desc_elem is not None and desc_elem.text:
                cal_params['Description'] = desc_elem.text
            
            # Use source filename as the dict key so every file is preserved.
            # Unique-configuration deduplication happens later when
            # build_calibration_key() generates standardized filenames.
            channel_key = xml_file.stem
            cal_data_by_channel[channel_key] = cal_params
            
            # Build a display label for the log message
            if 'Transducer' in cal_params:
                freq_start = cal_params.get('Frequency Start', 0)
                freq_end = cal_params.get('Frequency End', 0)
                display_label = f"{cal_params['Transducer']}_{int(freq_start/1000)}-{int(freq_end/1000)}kHz"
            elif 'Channel Name' in cal_params:
                display_label = cal_params['Channel Name']
            else:
                display_label = channel_key
            print(f"   Extracted parameters for {display_label}")
            
            # Print summary of key parameters
            if 'frequency' in cal_params:
                freq_arr = cal_params['frequency']
                print(f"      Frequency range: {freq_arr[0]:.0f} - {freq_arr[-1]:.0f} Hz ({len(freq_arr)} points)")
            if 'Gain' in cal_params:
                gain_arr = cal_params['Gain']
                if isinstance(gain_arr, list):
                    print(f"      Gain range: {min(gain_arr):.2f} - {max(gain_arr):.2f} dB")
                else:
                    print(f"      Gain: {gain_arr:.2f} dB")
            if 'TransmitPower' in cal_params:
                print(f"      Power: {cal_params['TransmitPower']:.0f} W")
            if 'Pulse Form' in cal_params:
                print(f"      Pulse Form: {cal_params['Pulse Form']}")
                
        except ET.ParseError as e:
            print(f"   Error parsing XML in {xml_file.name}: {e}")
        except Exception as e:
            print(f"   Error processing {xml_file.name}: {e}")
    
    print(f"\nSuccessfully parsed calibration data from {len(cal_data_by_channel)} files")
    
    # Reformat data for pipeline compatibility
    # Each channel becomes an entry, similar to EK60 frequency-based structure
    cal_data_refactored = _reformat_ek80_cal_data(cal_data_by_channel)
    
    # Log any missing parameters
    if output_logs_folder:
        _log_ek80_missing_params(output_logs_folder, cal_data_by_channel)
    
    return cal_data_refactored


def _reformat_ek80_cal_data(cal_data_by_channel):
    """Reformat EK80 calibration data for pipeline compatibility.
    
    Converts the per-channel dictionary format to a format similar to EK60,
    where each key maps to a list of values (one per channel). For FM data,
    array parameters remain as arrays within each channel's entry.
    
    Args:
        cal_data_by_channel: Dictionary with channel keys mapping to parameter dicts
        
    Returns:
        Dictionary with parameter names as keys and lists of values per channel
    """
    if not cal_data_by_channel:
        return {}
    
    # Convert to list format sorted by channel key
    channel_keys = sorted(cal_data_by_channel.keys())
    cal_data_list = [cal_data_by_channel[k] for k in channel_keys]
    
    # Display parsed data
    for channel_key in channel_keys:
        params = cal_data_by_channel[channel_key]
        print(f"\n   Channel: {channel_key}")
        for param, value in params.items():
            if isinstance(value, list):
                if len(value) > 3:
                    print(f"      {param}: [{value[0]:.4g}, ..., {value[-1]:.4g}] ({len(value)} values)")
                else:
                    print(f"      {param}: {value}")
            elif isinstance(value, float):
                print(f"      {param}: {value:.4g}")
            else:
                print(f"      {param}: {value}")
    
    # Refactor: each parameter becomes a list across channels.
    # First, collect all keys across all channels so that missing keys
    # are padded with None (prevents list-length misalignment).
    all_keys = {}
    for params in cal_data_list:
        for key in params:
            all_keys[key] = None  # insertion-ordered dict preserves key order

    cal_data_refactored = {key: [] for key in all_keys}
    for params in cal_data_list:
        for key in all_keys:
            cal_data_refactored[key].append(params.get(key))
    
    # Flatten single-value scalars that should be shared (Software version)
    # but only if they're the same across all channels.
    # Note: 'Date' and 'Description' are intentionally kept per-channel so
    # that each source file retains its own calibration date and comments.
    for scalar_key in ['SoftwareVersion', 'Sonar Software Name']:
        if scalar_key in cal_data_refactored:
            values = cal_data_refactored[scalar_key]
            # Use first non-None value
            first_val = next((v for v in values if v is not None), None)
            cal_data_refactored[scalar_key] = first_val
    
    return cal_data_refactored


def _log_ek80_missing_params(output_logs_folder, cal_data_by_channel, is_empty=False):
    """Log missing EK80 calibration parameters to flags file.
    
    Args:
        output_logs_folder: Path to folder for logs
        cal_data_by_channel: Parsed calibration data dictionary
        is_empty: True if no calibration files were found
    """
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
    
    for key in ["moderate_impacts", "large_impacts", "critical_impacts", 
                "data_irregularities", "missing_parameters"]:
        flags.setdefault(key, [])
    
    if is_empty:
        flags["missing_parameters"].append(
            "No EK80 XML calibration files found in specified folder"
        )
        print("Warning: No EK80 XML calibration files found")
    elif cal_data_by_channel:
        # Check for key parameters across all channels
        expected_parameters = [
            "frequency",
            "Gain",
            "SaCorrection", 
            "BeamWidthAthwartship",
            "BeamWidthAlongship",
            "AngleOffsetAthwartship",
            "AngleOffsetAlongship",
            "SoundVelocity",
            "AbsorptionCoefficient",
            "TransmitPower",
            "PulseLength",
            "SampleInterval",
            "Transducer",
            "Date",
            "Frequency Start",
            "Frequency End",
            "Pulse Form"
        ]
        
        for channel_key, params in cal_data_by_channel.items():
            missing = [p for p in expected_parameters if p not in params or params[p] is None]
            for param in missing:
                msg = f"Missing EK80 parameter '{param}' in channel {channel_key}"
                flags["missing_parameters"].append(msg)
                print(f"Warning: {msg}")
    
    with open(flags_file, 'w') as f:
        json.dump(flags, f, indent=2)


def convert_ek80_params_to_pipeline_format(cal_data_refactored):
    """Convert parsed EK80 parameters to the format expected by the pipeline.
    
    Maps EK80 XML parameter names to the standardized names used in
    full_pipeline.ipynb and standardized_file_lib.py.
    
    Args:
        cal_data_refactored: Output from extract_calibration_params_from_EK80_xml
        
    Returns:
        Tuple of (cal_params, env_params, other_params) dictionaries matching
        the format expected by standardized_file_lib.save_cal_params_to_standardized_file
    """
    # Map EK80 XML names to pipeline parameter names
    # Note: For FM data, these values are already arrays across frequencies
    
    cal_params = {
        # These may be arrays for FM mode
        "equivalent_beam_angle": cal_data_refactored.get("EquivalentBeamAngle"),
        "gain_correction": cal_data_refactored.get("Gain"),
        "sa_correction": cal_data_refactored.get("SaCorrection"),
        "beamwidth_athwartship": cal_data_refactored.get("BeamWidthAthwartship"),
        "beamwidth_alongship": cal_data_refactored.get("BeamWidthAlongship"),
        "angle_offset_athwartship": cal_data_refactored.get("AngleOffsetAthwartship"),
        "angle_offset_alongship": cal_data_refactored.get("AngleOffsetAlongship"),
        # Angle sensitivity not typically in EK80 cal results
        "angle_sensitivity_athwartship": None,
        "angle_sensitivity_alongship": None,
    }
    
    # Extract single sound_speed value and warn if values differ across channels
    sound_velocity_raw = cal_data_refactored.get("SoundVelocity")
    sound_velocity = None
    if sound_velocity_raw is not None:
        if isinstance(sound_velocity_raw, list) and len(sound_velocity_raw) > 0:
            # Check if all values are the same
            unique_values = set(v for v in sound_velocity_raw if v is not None)
            if len(unique_values) > 1:
                print(f"WARNING: Different sound speed values found across channels: {unique_values}")
                print(f"         Using the first value: {sound_velocity_raw[0]} m/s")
            sound_velocity = sound_velocity_raw[0]
        else:
            sound_velocity = sound_velocity_raw
    
    # Extract single values for temperature, salinity, pH (same logic as sound_speed)
    def _extract_single_env_value(values, param_name, units=""):
        """Helper to extract single value from potentially array environmental params."""
        if values is None:
            return None
        if isinstance(values, list) and len(values) > 0:
            unique_vals = set(v for v in values if v is not None)
            if len(unique_vals) > 1:
                print(f"WARNING: Different {param_name} values found across channels: {sorted(unique_vals)}")
                print(f"         Using the first value: {values[0]}{units}")
            return values[0]
        return values
    
    temperature = _extract_single_env_value(
        cal_data_refactored.get("Temperature"), "temperature", " degC"
    )
    salinity = _extract_single_env_value(
        cal_data_refactored.get("Salinity"), "salinity", " psu"
    )
    ph = _extract_single_env_value(
        cal_data_refactored.get("pH"), "pH", ""
    )
    
    env_params = {
        "sound_speed": sound_velocity,
        "sound_absorption": None,
        "temperature": temperature,
        "salinity": salinity,
        "pH": ph,
    }
    
    # Handle absorption - already in dB/m from EK80 XML (native unit)
    # Absorption is a single scalar per channel (even for FM mode)
    # Note: Use "is not None" check to preserve 0.0 values
    absorption_dB_m = cal_data_refactored.get("AbsorptionCoefficient")
    if absorption_dB_m is not None:
        # Already in dB/m, pass through directly
        env_params["sound_absorption"] = absorption_dB_m
    
    # Build channel names from transducer + transceiver info
    transducers = cal_data_refactored.get("Transducer", [])
    transceiver_serials = cal_data_refactored.get("Transceiver Serial", [])
    channel_names = cal_data_refactored.get("Channel Name", [])
    
    # Use channel names if available, otherwise construct from components
    if channel_names and any(channel_names):
        channels = channel_names if isinstance(channel_names, list) else [channel_names]
    elif transducers:
        channels = []
        for i, td in enumerate(transducers if isinstance(transducers, list) else [transducers]):
            serial = transceiver_serials[i] if isinstance(transceiver_serials, list) and i < len(transceiver_serials) else ""
            channels.append(f"WBT {serial} {td}" if serial else td)
    else:
        channels = []
    
    # Extract nominal transducer frequency from transducer model names
    # For EK80 XML cal files, the Transducer Name (e.g., "ES38-7") encodes the
    # nominal CW frequency.  We extract it via regex since the XML cal file
    # does not store the frequency directly outside the FM sweep array.
    nominal_transducer_frequency = []
    if transducers:
        td_list = transducers if isinstance(transducers, list) else [transducers]
        for td_name in td_list:
            nominal_transducer_frequency.append(
                extract_nominal_frequency_from_transducer_model(td_name)
            )
    
    # Extract single value for sonar software version/name (same for all channels)
    sonar_software_version = cal_data_refactored.get("SoftwareVersion")
    if isinstance(sonar_software_version, list) and len(sonar_software_version) > 0:
        sonar_software_version = sonar_software_version[0]
    sonar_software_name = cal_data_refactored.get("Sonar Software Name")
    if isinstance(sonar_software_name, list) and len(sonar_software_name) > 0:
        sonar_software_name = sonar_software_name[0]
    
    other_params = {
        "channel": channels,
        "frequency_nominal": cal_data_refactored.get("frequency"),
        "sonar_software_version": sonar_software_version,
        "sonar_software_name": sonar_software_name,
        "transmit_power": cal_data_refactored.get("TransmitPower"),
        "transmit_duration_nominal": cal_data_refactored.get("PulseLength"),
        "transmit_bandwidth": None,  # Calculate from frequency range if needed
        "sample_interval": cal_data_refactored.get("SampleInterval"),
        "transducer": transducers,
        "transducer_serial": cal_data_refactored.get("Transducer Serial"),
        "transceiver_serial": transceiver_serials,
        "date": cal_data_refactored.get("Date"),
        "comments": cal_data_refactored.get("Description"),
        "source_filenames_by_channel": cal_data_refactored.get("source_filenames"),
        "source_file_type": ".xml",
        # EK80-specific parameters
        "frequency_start": cal_data_refactored.get("Frequency Start"),
        "frequency_end": cal_data_refactored.get("Frequency End"),
        "pulse_form": cal_data_refactored.get("Pulse Form Code"),  # 0=CW, 1=FM
        "pulse_form_name": cal_data_refactored.get("Pulse Form"),  # "LFM" or "CW"
        "beam_type": cal_data_refactored.get("Beam Type"),
        "sphere_diameter": cal_data_refactored.get("Sphere Diameter"),
        "sphere_material": cal_data_refactored.get("Sphere Material"),
        "sphere_name": cal_data_refactored.get("Sphere Name"),
        "nominal_transducer_frequency": nominal_transducer_frequency if nominal_transducer_frequency else None,
        "transceiver_type": cal_data_refactored.get("Transceiver Type"),
    }
    
    # Calculate transmit_bandwidth from frequency range for FM
    freq_starts = cal_data_refactored.get("Frequency Start")
    freq_ends = cal_data_refactored.get("Frequency End")
    if freq_starts is not None and freq_ends is not None:
        if isinstance(freq_starts, list):
            other_params["transmit_bandwidth"] = [
                (end - start) if (end and start) else None
                for start, end in zip(freq_starts, freq_ends)
            ]
        elif freq_starts and freq_ends:
            other_params["transmit_bandwidth"] = freq_ends - freq_starts
    
    return cal_params, env_params, other_params


def convert_ek60_params_to_pipeline_format(cal_data_refactored):
    """Convert parsed EK60 parameters to the format expected by the pipeline.
    
    Maps EK60 .cal file parameter names to the standardized names used in
    full_pipeline.ipynb and standardized_file_lib.py.
    
    Args:
        cal_data_refactored: Output from extract_calibration_params_from_EK60_report
        
    Returns:
        Tuple of (cal_params, env_params, other_params) dictionaries matching
        the format expected by standardized_file_lib.save_cal_params_to_standardized_file
    """
    cal_params = {
        "equivalent_beam_angle": cal_data_refactored.get("Two Way Beam Angle"),
        "gain_correction": cal_data_refactored.get("Transducer Gain"),
        "sa_correction": cal_data_refactored.get("SaCorrection"),
        "beamwidth_athwartship": cal_data_refactored.get("Athw. Beam Angle"),
        "beamwidth_alongship": cal_data_refactored.get("Along. Beam Angle"),
        "angle_offset_athwartship": cal_data_refactored.get("Athw. Offset Angle"),
        "angle_offset_alongship": cal_data_refactored.get("Along. Offset Angle"),
        "angle_sensitivity_athwartship": cal_data_refactored.get("Athw. Angle Sens."),
        "angle_sensitivity_alongship": cal_data_refactored.get("Along. Angle Sens."),
    }
    
    # Sound velocity is a single value, absorption is per-frequency in dB/km
    # Check if values differ across channels and warn if so
    sound_velocity_raw = cal_data_refactored.get("Sound Velocity")
    sound_velocity = None
    if sound_velocity_raw is not None:
        if isinstance(sound_velocity_raw, list) and len(sound_velocity_raw) > 0:
            unique_values = set(v for v in sound_velocity_raw if v is not None)
            if len(unique_values) > 1:
                print(f"WARNING: Different sound speed values found across channels: {unique_values}")
                print(f"         Using the first value: {sound_velocity_raw[0]} m/s")
            sound_velocity = sound_velocity_raw[0]
        else:
            sound_velocity = sound_velocity_raw
    
    # Convert absorption from dB/km to dB/m
    # Note: Use "is not None" check to preserve 0.0 values
    absorption_km = cal_data_refactored.get("Absorption Coeff.")
    sound_absorption = None
    if absorption_km is not None:
        if isinstance(absorption_km, list):
            sound_absorption = [
                round(a / 1000, 10) if a is not None else None for a in absorption_km
            ]
        else:
            sound_absorption = round(absorption_km / 1000, 10) if absorption_km is not None else None
    
    env_params = {
        "sound_speed": sound_velocity,
        "sound_absorption": sound_absorption,
    }
    
    # Convert pulse duration from ms to seconds and sample interval from m to s
    pulse_duration = cal_data_refactored.get("Pulse Duration")
    if pulse_duration is not None:
        if isinstance(pulse_duration, list):
            pulse_duration = [round(d / 1000, 10) for d in pulse_duration]
        else:
            pulse_duration = round(pulse_duration / 1000, 10)
    
    # Convert receiver bandwidth from kHz to Hz
    bandwidth = cal_data_refactored.get("Receiver Bandwidth")
    if bandwidth is not None:
        if isinstance(bandwidth, list):
            bandwidth = [b * 1000 for b in bandwidth]
        else:
            bandwidth = bandwidth * 1000
    
    # Convert sample interval from meters to seconds (using sound velocity)
    sample_interval_m = cal_data_refactored.get("Sample Interval")
    sample_interval = None
    if sample_interval_m is not None and sound_velocity:
        if isinstance(sample_interval_m, list):
            sample_interval = [round(s / sound_velocity, 10) for s in sample_interval_m]
        else:
            sample_interval = round(sample_interval_m / sound_velocity, 10)
    
    # Extract single value for sonar software version (same for all channels)
    sonar_software_version = cal_data_refactored.get("Sounder Type Version")
    if isinstance(sonar_software_version, list) and len(sonar_software_version) > 0:
        sonar_software_version = sonar_software_version[0]
    
    other_params = {
        "channel": cal_data_refactored.get("Transceiver"),
        "frequency_nominal": cal_data_refactored.get("frequency"),
        "sonar_software_version": sonar_software_version,
        "transmit_power": cal_data_refactored.get("Power"),
        "transmit_duration_nominal": pulse_duration,
        "transmit_bandwidth": bandwidth,
        "sample_interval": sample_interval,
        "transducer": cal_data_refactored.get("Transducer"),
        "date": cal_data_refactored.get("Date"),
        "comments": cal_data_refactored.get("Comments"),
        "source_filenames_by_channel": cal_data_refactored.get("source_filenames"),
        "source_file_type": ".cal",
        # For EK60, nominal_transducer_frequency equals the channel frequency (as scalar per channel)
        "nominal_transducer_frequency": cal_data_refactored.get("frequency"),
    }
    
    return cal_params, env_params, other_params


def detect_calibration_file_type(cal_folder):
    """Detect the type of calibration files in a folder.
    
    Args:
        cal_folder: Path to folder containing calibration files
        
    Returns:
        str: "EK60" if .cal files found, "EK80" if .xml files found,
             "MIXED" if both found, "UNKNOWN" if neither found
    """
    cal_folder = Path(cal_folder)
    
    cal_files = list(cal_folder.glob('*.cal'))
    xml_files = list(cal_folder.glob('*.xml'))
    
    has_cal = len(cal_files) > 0
    has_xml = len(xml_files) > 0
    
    if has_cal and has_xml:
        return "MIXED"
    elif has_cal:
        return "EK60"
    elif has_xml:
        return "EK80"
    else:
        return "UNKNOWN"


def extract_and_convert_calibration_params(cal_folder, nc_frequencies=None, output_logs_folder=None):
    """Auto-detect calibration file type and extract parameters in pipeline format.
    
    This is the main unified entry point for parsing calibration files.
    It automatically detects whether the folder contains EK60 (.cal) or 
    EK80 (.xml) calibration files and calls the appropriate parser.
    
    Args:
        cal_folder: Path to folder containing calibration files (.cal or .xml)
        nc_frequencies: Array of frequencies for sorting (required for EK60,
                       optional for EK80). If None for EK60, frequencies are
                       sorted in ascending order.
        output_logs_folder: Path to folder for saving log files (optional)
        
    Returns:
        Tuple of (cal_params, env_params, other_params, file_type) where:
        - cal_params: Calibration parameters dict
        - env_params: Environmental parameters dict
        - other_params: Other parameters dict
        - file_type: "EK60" or "EK80" indicating what was parsed
        
    Raises:
        FileNotFoundError: If no calibration files found
        ValueError: If mixed file types found (both .cal and .xml)
    """
    cal_folder = Path(cal_folder)
    file_type = detect_calibration_file_type(cal_folder)
    
    if file_type == "UNKNOWN":
        raise FileNotFoundError(
            f"No calibration files found in {cal_folder}. "
            "Expected .cal (EK60) or .xml (EK80) files."
        )
    
    if file_type == "MIXED":
        raise ValueError(
            f"Mixed calibration file types found in {cal_folder}. "
            "Please separate EK60 (.cal) and EK80 (.xml) files into different folders."
        )
    
    print(f"Detected calibration file type: {file_type}")
    
    # Sort frequencies if provided (callers can pass an unsorted set or list)
    if nc_frequencies is not None:
        nc_frequencies = sorted(nc_frequencies)
    
    if file_type == "EK60":
        # For EK60, we need frequencies for sorting
        if nc_frequencies is None:
            # Auto-discover frequencies from .cal files
            cal_files = list(cal_folder.glob('*.cal'))
            nc_frequencies = []
            for cal_file in cal_files:
                try:
                    with open(cal_file, 'r') as f:
                        content = f.read()
                    for line in content.split('\n'):
                        if 'Frequency' in line and 'Hz' in line:
                            parts = line.split()
                            for i, p in enumerate(parts):
                                if p == 'Frequency' and i + 1 < len(parts):
                                    freq = float(parts[i + 1])
                                    nc_frequencies.append(freq)
                                    break
                            break
                except:
                    pass
            nc_frequencies = sorted(set(nc_frequencies))
            print(f"Auto-detected frequencies: {nc_frequencies} Hz")
        
        raw_params = extract_calibration_params_from_EK60_report(
            cal_folder, nc_frequencies, output_logs_folder
        )
        cal_params, env_params, other_params = convert_ek60_params_to_pipeline_format(raw_params)
        
    else:  # EK80
        raw_params = extract_calibration_params_from_EK80_xml(
            cal_folder, output_logs_folder
        )
        cal_params, env_params, other_params = convert_ek80_params_to_pipeline_format(raw_params)
    
    return cal_params, env_params, other_params, file_type


