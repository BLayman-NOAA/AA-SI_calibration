"""Low-level readers for Simrad EK60/EK80 raw files.

Provides binary datagram parsing, XML configuration extraction, GPS/NMEA
coordinate extraction, and channel-configuration export used by the rest of
the calibration pipeline.
"""

from pathlib import Path
import json
import re
from datetime import datetime, timedelta
from struct import unpack

import pytz
from lxml import etree as ET
try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None



def detect_instrument_type(raw_path):
    """Detect whether a raw file is EK60 or EK80 based on datagram types.
    
    EK60 uses CON0/RAW0 datagrams, EK80 uses XML0/RAW3 datagrams.
    """
    with open(raw_path, "rb") as fid:
        while True:
            header = fid.read(16)
            if len(header) < 16:
                break
            dg_size, dg_type, _ = unpack("=I4sQ", header)
            
            if dg_type == b"CON0":
                return "EK60"
            if dg_type == b"XML0":
                return "EK80"
            
            fid.seek(dg_size - 8, 1)
    
    return "UNKNOWN"


# Source location documentation

EK60_SOURCES = {
    "channel_id": (
        "CON0 > transceiver_record[n] > channel_id | "
        "Absolute offset: 544 + (n * 320) + 0, read 128 bytes as string"
    ),
    "transceiver_id": (
        "CON0 > transceiver_record[n] > channel_id | "
        "Absolute offset: 544 + (n * 320) + 0, read 128 bytes as string, "
        "parse 12-char hex via regex: [0-9a-fA-F]{12} (ethernet address for GPT)"
    ),
    "transceiver_model": (
        "CON0 > transceiver_record[n] > channel_id | "
        "first whitespace-separated token (always 'GPT' for EK60)"
    ),
    "transceiver_ethernet_address": (
        "Same as transceiver_id for EK60 - CON0 > channel_id, "
        "12-char hex parsed via regex: [0-9a-fA-F]{12}"
    ),
    "transceiver_serial_number": "NOT AVAILABLE in EK60 raw files",
    "transceiver_number": (
        "CON0 > transceiver_record[n] > channel_id | "
        "parse numeric token after 12-char hex, e.g., '... 3-2 ...' -> 3"
    ),
    "transceiver_port": (
        "CON0 > transceiver_record[n] > channel_id | "
        "parse numeric token after hyphen, e.g., '... 3-2 ...' -> 2; absent if no hyphen"
    ),
    "multiplexing_found": (
        "Derived: True if same transceiver_number appears with multiple transceiver_port values | "
        "Stored at channel level"
    ),
    "channel_instance_number": (
        "EK60 always uses 1 (single instance per channel) | "
        "Not present in raw file - default value"
    ),
    "transducer_serial_number": "NOT AVAILABLE in EK60 raw files",
    "transducer_model": (
        "CON0 > transceiver_record[n] > channel_id | "
        "last whitespace-separated token (e.g., 'ES38B')"
    ),
    "frequency": (
        "CON0 > transceiver_record[n] > frequency | "
        "Absolute offset: 544 + (n * 320) + 132, 4-byte little-endian float"
    ),
    "transmit_duration_nominal": "RAW0 > pulse_length | Offset 16-19 within RAW0 body, 4-byte float",
    "transmit_power": "RAW0 > transmit_power | Offset 12-15 within RAW0 body, 4-byte float",
    "pulse_form": "Implicit: EK60 is always CW (narrowband) - not stored in raw file",
    "frequency_start": "Implicit: equals frequency for CW mode",
    "frequency_end": "Implicit: equals frequency for CW mode",
    "nominal_transducer_frequency": (
        "CON0 > transceiver_record[n] > frequency | "
        "Same as frequency for EK60 (always CW). Stored as scalar."
    ),
}

EK80_SOURCES = {
    "channel_id": "XML0 (Configuration) > Transceivers > Transceiver > Channels > Channel[@ChannelID]",
    "transceiver_id": (
        "XML0 (Configuration) > Transceivers > Transceiver[@TransceiverName] - "
        "parsed as second token (e.g., 'GPT 009072069099' -> '009072069099')"
    ),
    "transceiver_model": "XML0 (Configuration) > Transceivers > Transceiver[@TransceiverType]",
    "transceiver_ethernet_address": "XML0 (Configuration) > Transceivers > Transceiver[@EthernetAddress]",
    "transceiver_serial_number": (
        "XML0 (Configuration) > Transceivers > Transceiver[@SerialNumber] - "
        "may be '0' for GPT units which use EthernetAddress as identifier"
    ),
    "transceiver_number": "XML0 (Configuration) > Transceivers > Transceiver[@TransceiverNumber]",
    "multiplexing_found": (
        "XML0 (Configuration) > Transceivers > Transceiver[@Multiplexing] - "
        "boolean flag (0=false, non-zero=true) stored at channel level per transceiver"
    ),
    "channel_instance_number": (
        "Extracted from ChannelID suffix '_<number>' (e.g., 'WBT 978217-15 ES38-7_2' -> 2) | "
        "Defaults to 1 if no suffix present"
    ),
    "transceiver_port": (
        "XML0 (Configuration) > ... > Channel[@HWChannelConfiguration] - "
        "Hardware channel/port on the WBT transceiver (e.g., '15' from 'WBT 978217-15 ES38-7')"
    ),
    "transducer_serial_number": (
        "XML0 (Configuration) > ... > Transducer[@SerialNumber] - "
        "treated as None/missing when value is '0' (not a real serial number)"
    ),
    "transducer_model": "XML0 (Configuration) > ... > Transducer[@TransducerName]",
    "frequency": "XML0 (Configuration) > ... > Transducer[@Frequency]",
    "transmit_duration_nominal": "XML0 (Parameter) > Channel[@PulseDuration]",
    "transmit_power": "XML0 (Parameter) > Channel[@TransmitPower]",
    "pulse_form": "XML0 (Parameter) > Channel[@PulseForm] - 0=CW, 1=FM",
    "frequency_start": "For CW: equals frequency. For FM: Transducer[@FrequencyMinimum]",
    "frequency_end": "For CW: equals frequency. For FM: Transducer[@FrequencyMaximum]",
    "nominal_transducer_frequency": (
        "XML0 (Configuration) > ... > Transducer[@Frequency] | "
        "Nominal CW operating frequency of the transducer (Hz). "
        "Always available regardless of CW/FM mode."
    ),
}

GPS_SOURCES = {
    "nmea_datagram": (
        "NME0 datagrams contain NMEA 0183 GPS sentences. Common sentence types: "
        "GPGGA (GPS fix), GPGLL (Geographic Position), GPRMC (Recommended Minimum). "
        "Also supports integrated nav: INGGA, INGLL, INRMC, INGGK."
    ),
    "latitude": (
        "Parsed from NMEA sentence fields. Format: ddmm.mmmm with N/S hemisphere indicator. "
        "GPGGA: field[2] (lat) + field[3] (N/S). "
        "GPGLL: field[1] (lat) + field[2] (N/S). "
        "GPRMC: field[3] (lat) + field[4] (N/S)."
    ),
    "longitude": (
        "Parsed from NMEA sentence fields. Format: dddmm.mmmm with E/W hemisphere indicator. "
        "GPGGA: field[4] (lon) + field[5] (E/W). "
        "GPGLL: field[3] (lon) + field[4] (E/W). "
        "GPRMC: field[5] (lon) + field[6] (E/W)."
    ),
    "timestamp": (
        "Datagram header contains 64-bit NT timestamp (100ns intervals since 1601-01-01). "
        "NMEA sentence may also contain time (hhmmss.ss format) but not always date."
    ),
}


def _clean_value(value):
    """Recursively clean bytes/bytearray values to decoded strings."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace").strip("\x00")
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_clean_value(v) for v in value)
    return value


# Import string identifier conversion from standardized_file_lib
from .standardized_file_lib import ensure_string_identifiers as _ensure_string_identifiers


def _pretty_dict(title, payload):
    """Print a dictionary as formatted JSON with a title."""
    print(title)
    cleaned = _clean_value(payload)
    if isinstance(cleaned, str):
        stripped = cleaned.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                cleaned = json.loads(stripped)
            except json.JSONDecodeError:
                pass
    print(json.dumps(cleaned, indent=2, default=str))


def save_yaml(data, output_path):
    """Save data to a YAML file.

    Args:
        data: Any JSON-serializable structure or nested dict/list of values.
        output_path: Path to the output YAML file.
    """
    if yaml is None:
        raise ImportError("PyYAML is required to save YAML. Install with `pip install pyyaml`.")

    cleaned = _clean_value(data)
    cleaned = _ensure_string_identifiers(cleaned)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            cleaned,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )


def nt_to_datetime(nt_timestamp):
    """Convert 64-bit NT timestamp to Python datetime (UTC)."""
    microseconds = nt_timestamp / 10
    seconds, microseconds = divmod(microseconds, 1_000_000)
    days, seconds = divmod(seconds, 86400)
    return datetime(1601, 1, 1, 0, 0, 0, 0, pytz.UTC) + timedelta(days, seconds, microseconds)


def truncate_to_milliseconds(dt):
    """Truncate datetime to nearest millisecond (discard sub-ms precision)."""
    if dt is None:
        return None
    truncated_microseconds = (dt.microsecond // 1000) * 1000
    return dt.replace(microsecond=truncated_microseconds)


def _xml_element_to_dict(elem):
    """Convert an lxml Element to a nested dictionary."""
    node = {"tag": elem.tag}
    if elem.attrib:
        node["attributes"] = dict(elem.attrib)
    text = (elem.text or "").strip()
    if text:
        node["text"] = text
    children = [_xml_element_to_dict(child) for child in elem]
    if children:
        node["children"] = children
    return node


def _iter_datagrams(raw_path, read_types=(b"XML0", b"NME0")):
    """Walk a Simrad raw file once, yielding one tuple per datagram.

    The datagram envelope (leading size, type, NT timestamp, body, trailing
    size) is identical for EK60 and EK80 files, so this walker is shared by all
    the extraction functions.

    Args:
        raw_path: Path to the raw file.
        read_types: Datagram type codes whose body bytes should be read. For
            these types the trailing size is stripped so body is the payload
            only. All other types are skipped with a seek and yield a body of
            None, so the large RAW3 sample payloads are never transferred.

    Yields:
        Tuples of (dg_type, timestamp, body), where timestamp is a UTC datetime
        or None when the raw NT value is out of range.
    """
    with open(raw_path, "rb") as fid:
        while True:
            header = fid.read(16)
            if len(header) < 16:
                break
            dg_size, dg_type, nt_timestamp = unpack("=I4sQ", header)

            try:
                timestamp = nt_to_datetime(nt_timestamp)
            except (ValueError, OverflowError):
                timestamp = None

            if dg_type in read_types:
                rest = fid.read(dg_size - 8)
                yield dg_type, timestamp, rest[: dg_size - 12]
            else:
                fid.seek(dg_size - 8, 1)
                yield dg_type, timestamp, None


def _read_xml_roots(raw_path):
    """Yield XML root elements from XML0 datagrams in an EK80 raw file."""
    parser = ET.XMLParser(resolve_entities=False, recover=True)
    for dg_type, _timestamp, body in _iter_datagrams(raw_path, read_types=(b"XML0",)):
        if dg_type != b"XML0":
            continue
        try:
            yield ET.fromstring(body, parser=parser)
        except ET.XMLSyntaxError:
            continue


def read_ek80_xml_as_dict(raw_path):
    """Return list of XML roots from EK80 file converted to dictionaries."""
    return [_xml_element_to_dict(root) for root in _read_xml_roots(raw_path)]


def prune_frequencypar_nodes(node, _seen_channels=None):
    """Remove FrequencyPar nodes and deduplicate Parameter nodes by ChannelID.
    
    - FrequencyPar nodes (and their children) are removed entirely
    - Parameter nodes are deduplicated: only the first occurrence for each 
      unique ChannelID is kept
    """
    if _seen_channels is None:
        _seen_channels = set()
    
    if isinstance(node, list):
        return [
            pruned for item in node
            if (pruned := prune_frequencypar_nodes(item, _seen_channels)) is not None
        ]
    
    if not isinstance(node, dict):
        return node
    
    # Remove FrequencyPar nodes entirely
    if node.get("tag") == "FrequencyPar":
        return None
    
    # Deduplicate Parameter nodes by ChannelID
    if node.get("tag") == "Parameter":
        channel_id = None
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("tag") == "Channel":
                channel_id = child.get("attributes", {}).get("ChannelID")
                break
        if channel_id:
            if channel_id in _seen_channels:
                return None
            _seen_channels.add(channel_id)
    
    # Process children recursively
    pruned = {k: v for k, v in node.items() if k != "children"}
    children = node.get("children")
    if children:
        kept = [
            cleaned for child in children
            if (cleaned := prune_frequencypar_nodes(child, _seen_channels)) is not None
        ]
        if kept:
            pruned["children"] = kept
    return pruned


def parse_nmea_latlon(nmea_string):
    """Parse latitude and longitude from an NMEA sentence string.
    
    Supports GPGGA, GPGLL, GPRMC, INGGA, INGLL, INRMC, INGGK sentence types.
    
    Args:
        nmea_string: Raw NMEA sentence string (e.g., "$GPGGA,123519,...")
    
    Returns:
        tuple: (latitude, longitude) in decimal degrees, or (None, None) if parsing fails.
               South latitudes and West longitudes are negative.
    """
    def ddmm_to_decimal(ddmm_str, direction, is_longitude=False):
        """Convert NMEA ddmm.mmmm format to decimal degrees."""
        try:
            ddmm_str = ddmm_str.strip()
            if not ddmm_str:
                return None
            
            # Split on decimal point
            if '.' not in ddmm_str:
                return None
            
            whole, frac = ddmm_str.split('.')
            
            if is_longitude:
                # Longitude: dddmm.mmmm
                if len(whole) < 3:
                    return None
                degrees = int(whole[:-2])
                minutes = float(whole[-2:] + '.' + frac)
            else:
                # Latitude: ddmm.mmmm
                if len(whole) < 2:
                    return None
                degrees = int(whole[:-2]) if len(whole) > 2 else 0
                minutes = float(whole[-2:] + '.' + frac)
            
            decimal = degrees + minutes / 60.0
            
            # Apply hemisphere sign
            if direction in ('S', 'W'):
                decimal = -decimal
            
            return round(decimal, 6)
        except (ValueError, IndexError):
            return None
    
    try:
        # Clean the string - handle bytes and escape chars
        if isinstance(nmea_string, bytes):
            nmea_string = nmea_string.decode('utf-8', errors='replace')
        nmea_string = nmea_string.replace("\\x00", "").replace("\x00", "").strip()
        
        # Find the actual NMEA sentence (starts with $ or talker ID)
        match = re.search(r'\$?([A-Z]{2}(?:GGA|GLL|RMC|GGK))[,](.+?)(?:\*[0-9A-Fa-f]{2})?(?:\\|$|\x00)', nmea_string)
        if not match:
            return None, None
        
        sentence_type = match.group(1)
        fields = match.group(2).split(',')
        
        lat, lon = None, None
        lat_dir, lon_dir = None, None
        
        if sentence_type.endswith('GGA'):
            # $xxGGA,time,lat,N/S,lon,E/W,quality,numSV,HDOP,alt,M,sep,M,diffAge,diffStation*cs
            if len(fields) >= 5:
                lat = fields[1]
                lat_dir = fields[2]
                lon = fields[3]
                lon_dir = fields[4]
        
        elif sentence_type.endswith('GLL'):
            # $xxGLL,lat,N/S,lon,E/W,time,status,mode*cs
            if len(fields) >= 4:
                lat = fields[0]
                lat_dir = fields[1]
                lon = fields[2]
                lon_dir = fields[3]
        
        elif sentence_type.endswith('RMC'):
            # $xxRMC,time,status,lat,N/S,lon,E/W,spd,cog,date,mv,mvE,mode*cs
            if len(fields) >= 6:
                lat = fields[2]
                lat_dir = fields[3]
                lon = fields[4]
                lon_dir = fields[5]
        
        elif sentence_type.endswith('GGK'):
            # $xxGGK,time,lat,N/S,lon,E/W,...
            if len(fields) >= 5:
                lat = fields[1]
                lat_dir = fields[2]
                lon = fields[3]
                lon_dir = fields[4]
        
        if lat and lon and lat_dir and lon_dir:
            return (
                ddmm_to_decimal(lat, lat_dir, is_longitude=False),
                ddmm_to_decimal(lon, lon_dir, is_longitude=True)
            )
        
        return None, None
    
    except Exception:
        return None, None


def _new_gps_state():
    """Fresh accumulator for GPS/NME0 extraction."""
    return {
        "first_gps": None,
        "last_gps": None,
        "nmea_count": 0,
        "valid_gps_count": 0,
        "sentence_types": set(),
    }


def _lean_fix(gps_fix):
    """Position-only view of a fix, dropping the diagnostic ``nmea_sentence``."""
    return {
        "latitude": gps_fix["latitude"],
        "longitude": gps_fix["longitude"],
        "timestamp": gps_fix["timestamp"],
    }


def _accumulate_nme0(nmea_body, timestamp, state):
    """Update the GPS state dict from a single NME0 datagram body.

    Shared by extract_gps_data and scan_ek80_file so both apply identical NMEA
    parsing.

    Args:
        nmea_body: Raw NME0 datagram payload bytes.
        timestamp: Datagram timestamp, or None if unparseable.
        state: Accumulator dict from _new_gps_state, updated in place.

    Returns:
        The parsed fix dict (latitude, longitude, timestamp, nmea_sentence) when
        the datagram held a valid position, else None. extract_gps_data uses the
        returned fix to build the optional track; scan_ek80_file ignores it.
    """
    state["nmea_count"] += 1

    try:
        nmea_string = nmea_body.decode("utf-8", errors="replace").strip("\x00")
    except (UnicodeDecodeError, AttributeError):
        return None

    type_match = re.search(r'\$?([A-Z]{2}(?:GGA|GLL|RMC|GGK))', nmea_string)
    if type_match:
        state["sentence_types"].add(type_match.group(1))

    lat, lon = parse_nmea_latlon(nmea_string)
    if lat is None or lon is None:
        return None

    state["valid_gps_count"] += 1
    gps_fix = {
        "latitude": lat,
        "longitude": lon,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "nmea_sentence": (
            nmea_string[:80] + "..." if len(nmea_string) > 80 else nmea_string
        ),
    }
    state["last_gps"] = gps_fix
    if state["first_gps"] is None:
        state["first_gps"] = gps_fix
    return gps_fix


def _finalize_gps_state(state, track=None):
    """Convert a GPS accumulator into the extract_gps_data return dict.

    Args:
        state: The summary accumulator from _new_gps_state.
        track: Optional list of fixes to attach under a ``track`` key. When
            None (the default) no ``track`` key is added, so first/last-only
            callers get the historical 5-key dict unchanged.
    """
    result = {
        "first_gps": state["first_gps"],
        "last_gps": state["last_gps"],
        "nmea_count": state["nmea_count"],
        "valid_gps_count": state["valid_gps_count"],
        "sentence_types": list(state["sentence_types"]),
    }
    if track is not None:
        result["track"] = track
    return result


def extract_gps_data(raw_path, include_track=True, include_nmea_sentence=False):
    """Extract GPS coordinates from a raw file's NMEA datagrams.

    Works with both EK60 and EK80 files. GPS data is stored in NME0 datagrams
    containing NMEA 0183 sentences (GPGGA, GPGLL, GPRMC, etc.).

    Args:
        raw_path: Path to the raw file
        include_track: If True (the default), also return a ``track`` list
            containing every valid fix, oldest first. Pass False to get only
            the first/last summary (used by the calibration pipeline so the
            emitted config stays compact).
        include_nmea_sentence: If True, each ``track`` entry also carries the
            raw ``nmea_sentence`` string; otherwise track entries are the lean
            ``{latitude, longitude, timestamp}`` subset. Only affects the
            track; ``first_gps``/``last_gps`` always include ``nmea_sentence``.

    Returns:
        dict with:
          - first_gps: dict with latitude, longitude, timestamp, nmea_sentence (or None)
          - last_gps: dict with latitude, longitude, timestamp, nmea_sentence (or None)
          - nmea_count: total number of NME0 datagrams found
          - valid_gps_count: number of datagrams with valid lat/lon
          - sentence_types: set of NMEA sentence types found
          - track: only when include_track - list of every valid fix, oldest
            first. track[0]/track[-1] correspond to first_gps/last_gps.
    """
    state = _new_gps_state()
    track = [] if include_track else None
    for dg_type, timestamp, body in _iter_datagrams(raw_path, read_types=(b"NME0",)):
        if dg_type == b"NME0":
            gps_fix = _accumulate_nme0(body, timestamp, state)
            if track is not None and gps_fix is not None:
                track.append(gps_fix if include_nmea_sentence else _lean_fix(gps_fix))
    return _finalize_gps_state(state, track)


def extract_datagram_timestamps(raw_path):
    """Extract timestamps from EK60 raw file datagrams.
    
    Returns dict with:
      - con0_timestamp: timestamp from CON0 datagram (first in file)
      - first_raw0_timestamp: timestamp from first RAW0 datagram (truncated to ms)
      - last_raw0_timestamp: timestamp from last RAW0 datagram (truncated to ms)
      - first_datagram_timestamp: earliest timestamp encountered
      - last_datagram_timestamp: latest timestamp encountered
      - raw0_count: total number of RAW0 datagrams
    """
    con0_timestamp = None
    first_raw0_timestamp = None
    last_raw0_timestamp = None
    first_datagram_timestamp = None
    last_datagram_timestamp = None
    raw0_count = 0
    
    with open(raw_path, "rb") as fid:
        while True:
            header = fid.read(16)
            if len(header) < 16:
                break
            
            dg_size, dg_type, nt_timestamp = unpack("=I4sQ", header)
            
            try:
                timestamp = nt_to_datetime(nt_timestamp)
            except (ValueError, OverflowError):
                fid.seek(dg_size - 8, 1)
                continue
            
            if first_datagram_timestamp is None:
                first_datagram_timestamp = timestamp
            last_datagram_timestamp = timestamp
            
            if dg_type == b"CON0" and con0_timestamp is None:
                con0_timestamp = timestamp
            
            if dg_type == b"RAW0":
                raw0_count += 1
                if first_raw0_timestamp is None:
                    first_raw0_timestamp = timestamp
                last_raw0_timestamp = timestamp
            
            fid.seek(dg_size - 8, 1)
    
    return {
        "con0_timestamp": con0_timestamp,
        "first_raw0_timestamp": truncate_to_milliseconds(first_raw0_timestamp),
        "last_raw0_timestamp": truncate_to_milliseconds(last_raw0_timestamp),
        "first_datagram_timestamp": first_datagram_timestamp,
        "last_datagram_timestamp": last_datagram_timestamp,
        "raw0_count": raw0_count,
    }


def _new_ek80_timestamp_state():
    """Fresh accumulator for EK80 datagram timestamp extraction."""
    return {
        "xml0_timestamp": None,
        "first_raw3_timestamp": None,
        "last_raw3_timestamp": None,
        "first_datagram_timestamp": None,
        "last_datagram_timestamp": None,
        "raw3_count": 0,
    }


def _accumulate_ek80_timestamp(dg_type, timestamp, state):
    """Update the EK80 timestamp state from one datagram.

    Datagrams whose NT timestamp could not be parsed (timestamp is None) are
    skipped.

    Args:
        dg_type: Datagram type code.
        timestamp: Datagram timestamp, or None if unparseable.
        state: Accumulator dict from _new_ek80_timestamp_state, updated in
            place.
    """
    if timestamp is None:
        return

    if state["first_datagram_timestamp"] is None:
        state["first_datagram_timestamp"] = timestamp
    state["last_datagram_timestamp"] = timestamp

    if dg_type == b"XML0" and state["xml0_timestamp"] is None:
        state["xml0_timestamp"] = timestamp

    if dg_type == b"RAW3":
        state["raw3_count"] += 1
        if state["first_raw3_timestamp"] is None:
            state["first_raw3_timestamp"] = timestamp
        state["last_raw3_timestamp"] = timestamp


def _finalize_ek80_timestamp_state(state):
    """Convert an EK80 timestamp accumulator into the return dict."""
    return {
        "xml0_timestamp": state["xml0_timestamp"],
        "first_raw3_timestamp": truncate_to_milliseconds(state["first_raw3_timestamp"]),
        "last_raw3_timestamp": truncate_to_milliseconds(state["last_raw3_timestamp"]),
        "first_datagram_timestamp": state["first_datagram_timestamp"],
        "last_datagram_timestamp": state["last_datagram_timestamp"],
        "raw3_count": state["raw3_count"],
    }


def extract_ek80_datagram_timestamps(raw_path):
    """Extract timestamps from EK80 raw file datagrams.
    
    EK80 uses RAW3 datagrams instead of RAW0.
    
    Returns dict with:
      - xml0_timestamp: timestamp from first XML0 datagram (configuration)
      - first_raw3_timestamp: timestamp from first RAW3 datagram (truncated to ms)
      - last_raw3_timestamp: timestamp from last RAW3 datagram (truncated to ms)
      - first_datagram_timestamp: earliest timestamp encountered
      - last_datagram_timestamp: latest timestamp encountered
      - raw3_count: total number of RAW3 datagrams
    """
    state = _new_ek80_timestamp_state()
    for dg_type, timestamp, _body in _iter_datagrams(raw_path, read_types=()):
        _accumulate_ek80_timestamp(dg_type, timestamp, state)
    return _finalize_ek80_timestamp_state(state)


def scan_ek80_file(raw_path):
    """Scan an EK80 raw file in a single pass.

    Walks the file once, reading only the datagram headers plus the small XML0
    and NME0 bodies and skipping the large RAW3 sample payloads. Produces all
    the pieces extract_ek80_file_config needs.

    Args:
        raw_path: Path to the EK80 raw file.

    Returns:
        A dict with keys:
            xml_dicts: XML configuration and parameter dicts, as
                read_ek80_xml_as_dict returns.
            timestamps: RAW3 and datagram timestamps, as
                extract_ek80_datagram_timestamps returns.
            gps_data: First and last GPS fixes, as extract_gps_data returns.
            metadata_start_time: The first datagram time formatted as
                %Y-%m-%dT%H:%M:%S, or None when the file has no parseable
                timestamps.
    """
    xml_parser = ET.XMLParser(resolve_entities=False, recover=True)
    xml_dicts = []
    ts_state = _new_ek80_timestamp_state()
    gps_state = _new_gps_state()

    for dg_type, timestamp, body in _iter_datagrams(
        raw_path, read_types=(b"XML0", b"NME0")
    ):
        _accumulate_ek80_timestamp(dg_type, timestamp, ts_state)
        if dg_type == b"XML0":
            try:
                root = ET.fromstring(body, parser=xml_parser)
            except ET.XMLSyntaxError:
                continue
            xml_dicts.append(_xml_element_to_dict(root))
        elif dg_type == b"NME0":
            _accumulate_nme0(body, timestamp, gps_state)

    first_dg = ts_state["first_datagram_timestamp"]
    metadata_start_time = (
        first_dg.strftime("%Y-%m-%dT%H:%M:%S") if first_dg else None
    )

    return {
        "xml_dicts": xml_dicts,
        "timestamps": _finalize_ek80_timestamp_state(ts_state),
        "gps_data": _finalize_gps_state(gps_state),
        "metadata_start_time": metadata_start_time,
    }


def extract_ek60_file_config(raw_path, reader, metadata=None):
    """Extract EK60 file configuration for calibration matching.
    
    Args:
        raw_path: Path to the raw file
        reader: SimradFileReader instance (already processed)
        metadata: Optional parsed metadata dict
    
    Returns a dict with:
      - filename, file_format
      - metadata_start_time, first_ping_time, last_ping_time
      - raw0_count, multiplexing_found
      - gps_data: first/last GPS coordinates with timestamps
      - channels: list of channel configs with transceiver/transducer identifiers
    """
    timestamps = extract_datagram_timestamps(raw_path)
    gps_data = extract_gps_data(raw_path, include_track=False)
    
    channels = []
    # Track transceiver_number -> set of transceiver_port values for multiplexing detection
    transceiver_ports = {}  # {transceiver_number: {port1, port2, ...}}
    
    transceivers = reader.config.get("transceivers", {})
    for txcvr in transceivers.values():
        channel_id = txcvr.get("channel_id", "")
        if isinstance(channel_id, (bytes, bytearray)):
            channel_id = channel_id.decode("utf-8", errors="replace").strip("\x00")
        
        # Parse channel_id: "GPT  38 kHz 0090720346bc 1-1 ES38B"
        tokens = channel_id.split() if channel_id else []
        
        # Ethernet address (12-char hex)
        match = re.search(r'([0-9a-fA-F]{12})', channel_id)
        transceiver_ethernet = match.group(1) if match else None
        
        # Transceiver model (first token) and transducer model (last token)
        transceiver_model = tokens[0] if tokens else None
        transducer_model = tokens[-1] if tokens else None
        
        # Transceiver number and transceiver_port (e.g., "3-1" -> number=3, port=1)
        transceiver_number = None
        transceiver_port = None
        channel_match = re.search(r'[0-9a-fA-F]{12}\s+(\d+)(?:-(\d+))?\s+\S+$', channel_id)
        if channel_match:
            transceiver_number = int(channel_match.group(1))
            transceiver_port = int(channel_match.group(2)) if channel_match.group(2) else 1
            # Track ports per transceiver for multiplexing detection
            if transceiver_number not in transceiver_ports:
                transceiver_ports[transceiver_number] = set()
            transceiver_ports[transceiver_number].add(transceiver_port)
        
        frequency = txcvr.get("frequency")
        
        # Get operational params from RAW0 channels
        freq_key = int(frequency) if frequency else None
        channel_params = reader.channels.get(freq_key, {})
        transmit_power = channel_params.get("transmit_power", reader.power)
        pulse_length = channel_params.get("pulse_length", reader.pulse_length)
        
        channels.append({
            "channel_id": channel_id,
            # Transceiver identifiers
            "transceiver_id": transceiver_ethernet,
            "transceiver_model": transceiver_model,
            "transceiver_ethernet_address": transceiver_ethernet,
            "transceiver_serial_number": None,  # Not available in EK60
            "transceiver_number": transceiver_number,
            "transceiver_port": transceiver_port,
            "channel_instance_number": 1,  # EK60 always uses single instance
            # Transducer identifiers
            "transducer_serial_number": None,  # Not available in EK60
            "transducer_model": transducer_model,
            # Channel configuration
            "frequency": frequency,
            "transmit_duration_nominal": pulse_length,
            "transmit_power": transmit_power,
            "pulse_form": "0",  # Always CW for EK60
            "frequency_start": frequency,
            "frequency_end": frequency,
            # For EK60, nominal_transducer_frequency equals the channel frequency
            "nominal_transducer_frequency": frequency,
            # Multiplexing - will be set after processing all channels
            "multiplexing_found": None,
        })
    
    # Determine multiplexing_found for each channel based on transceiver having multiple ports
    for channel in channels:
        txcvr_num = channel.get("transceiver_number")
        if txcvr_num is not None and txcvr_num in transceiver_ports:
            channel["multiplexing_found"] = len(transceiver_ports[txcvr_num]) > 1
        else:
            channel["multiplexing_found"] = False
    
    return {
        "filename": Path(raw_path).name,
        "file_format": reader.file_format,
        "metadata_start_time": metadata.get("START_TIME") if metadata else None,
        "first_ping_time": (
            timestamps["first_raw0_timestamp"].isoformat(timespec="milliseconds")
            if timestamps["first_raw0_timestamp"] else None
        ),
        "last_ping_time": (
            timestamps["last_raw0_timestamp"].isoformat(timespec="milliseconds")
            if timestamps["last_raw0_timestamp"] else None
        ),
        "raw0_count": timestamps["raw0_count"],
        "gps_data": gps_data,
        "channels": channels,
    }


def extract_ek80_file_config(
    raw_path,
    ek80_xml_dict,
    metadata_start_time=None,
    timestamps=None,
    gps_data=None,
):
    """Extract EK80 file configuration for calibration matching.
    
    Args:
        raw_path: Path to the raw file
        ek80_xml_dict: List of XML roots converted to dictionaries
        metadata_start_time: Precomputed value for the metadata_start_time
            field. Left as None when not provided.
        timestamps: Precomputed RAW3 and datagram timestamps, as returned by
            extract_ek80_datagram_timestamps. Computed on demand when None so
            the function still works on its own.
        gps_data: Precomputed GPS data, as returned by extract_gps_data.
            Computed on demand when None.

    Returns a dict with:
      - filename, metadata_start_time, first_ping_time, last_ping_time
      - raw3_count, multiplexing_found
      - gps_data: first/last GPS coordinates with timestamps
      - channels: list of channel configs with transceiver/transducer identifiers
    """
    if timestamps is None:
        timestamps = extract_ek80_datagram_timestamps(raw_path)
    if gps_data is None:
        gps_data = extract_gps_data(raw_path, include_track=False)

    # Build lookup tables from Configuration XML
    transceiver_info = {}
    transducer_info = {}
    parameter_info = {}
    
    for node in ek80_xml_dict:
        if node.get("tag") == "Configuration":
            _parse_ek80_configuration(node, transceiver_info, transducer_info)
        
        elif node.get("tag") == "Parameter":
            _parse_ek80_parameter(node, parameter_info)
    
    # Build channel configs
    channels = []
    for channel_id in transducer_info:
        txcvr = transceiver_info.get(channel_id, {})
        tducer = transducer_info.get(channel_id, {})
        params = parameter_info.get(channel_id, {})
        
        pulse_form = params.get("pulse_form", "0")
        frequency = tducer.get("frequency", 0)
        
        # For FM, use frequency range; for CW use center frequency
        if pulse_form == "1":
            # Prefer operational sweep limits from Parameter block if present
            start_freq = params.get("frequency_start")
            if start_freq is None:
                start_freq = tducer.get("freq_min", frequency)
            end_freq = params.get("frequency_end")
            if end_freq is None:
                end_freq = tducer.get("freq_max", frequency)
        else:
            # For CW, prefer the operational frequency from parameters when available
            param_frequency = params.get("frequency", frequency)
            if param_frequency == 0:
                param_frequency = frequency
            start_freq = param_frequency
            end_freq = start_freq
        
        channels.append({
            "channel_id": channel_id,
            "transceiver_id": txcvr.get("id"),
            "transceiver_model": txcvr.get("model"),
            "transceiver_ethernet_address": txcvr.get("ethernet_address"),
            "transceiver_serial_number": txcvr.get("serial_number"),
            "transceiver_number": txcvr.get("transceiver_number"),
            "transceiver_port": txcvr.get("transceiver_port"),
            "channel_instance_number": txcvr.get("channel_instance_number"),
            "multiplexing_found": txcvr.get("multiplexing_found"),
            "transducer_serial_number": tducer.get("serial"),
            "transducer_model": tducer.get("model"),
            "frequency": frequency,
            "nominal_transducer_frequency": frequency,  # Transducer[@Frequency] is the nominal CW frequency
            "transmit_duration_nominal": params.get("pulse_length"),
            "transmit_power": params.get("transmit_power"),
            "pulse_form": str(pulse_form),
            "frequency_start": start_freq,
            "frequency_end": end_freq,
        })
    
    return {
        "filename": Path(raw_path).name,
        "metadata_start_time": metadata_start_time,
        "first_ping_time": (
            timestamps["first_raw3_timestamp"].isoformat(timespec="milliseconds")
            if timestamps["first_raw3_timestamp"] else None
        ),
        "last_ping_time": (
            timestamps["last_raw3_timestamp"].isoformat(timespec="milliseconds")
            if timestamps["last_raw3_timestamp"] else None
        ),
        "raw3_count": timestamps["raw3_count"],
        "gps_data": gps_data,
        "channels": channels,
    }


def _parse_ek80_configuration(config_node, transceiver_info, transducer_info):
    """Parse EK80 Configuration XML node to populate transceiver/transducer info.
    
    Populates transceiver_info and transducer_info dictionaries keyed by channel_id.
    - channel_instance_number: extracted from ChannelID suffix "_<number>" (defaults to 1)
    - transceiver_port: from Channel[@HWChannelConfiguration] - hardware port on WBT
    - multiplexing_found: based on Multiplexing attribute (0=false, non-zero=true)
    """
    for child in config_node.get("children", []):
        if child.get("tag") != "Transceivers":
            continue
        
        for txcvr_node in child.get("children", []):
            if txcvr_node.get("tag") != "Transceiver":
                continue
            
            attrs = txcvr_node.get("attributes", {})
            
            # Parse transceiver_id from TransceiverName (e.g., "GPT 009072069099")
            txcvr_name = attrs.get("TransceiverName", "")
            match = re.match(r'^\s*\w+\s+(\S+)', txcvr_name)
            txcvr_id = match.group(1) if match else None
            
            txcvr_number = _safe_int(attrs.get("TransceiverNumber"))
            
            # Multiplexing attribute is a boolean flag (0=off, non-zero=on)
            multiplexing_flag = _safe_int(attrs.get("Multiplexing"))
            multiplexing_found = bool(multiplexing_flag and multiplexing_flag != 0)
            
            # Traverse to Channels > Channel > Transducer
            for channels_node in txcvr_node.get("children", []):
                if channels_node.get("tag") != "Channels":
                    continue
                
                channel_nodes = [
                    n for n in channels_node.get("children", [])
                    if n.get("tag") == "Channel"
                ]
                
                for channel_node in channel_nodes:
                    ch_attrs = channel_node.get("attributes", {})
                    channel_id = ch_attrs.get("ChannelID")
                    if not channel_id:
                        continue
                    
                    # Extract channel_instance_number from ChannelID suffix (e.g., "_2" in "WBT 978217-15 ES38-7_2")
                    instance_match = re.search(r'_(\d+)$', channel_id)
                    channel_instance_number = int(instance_match.group(1)) if instance_match else 1
                    
                    # transceiver_port from HWChannelConfiguration attribute
                    # This is the hardware channel/port on the WBT (e.g., "15")
                    hw_channel_config = ch_attrs.get("HWChannelConfiguration")
                    transceiver_port = _safe_int(hw_channel_config) if hw_channel_config else None
                    
                    transceiver_info[channel_id] = {
                        "id": txcvr_id,
                        "model": attrs.get("TransceiverType"),
                        "ethernet_address": attrs.get("EthernetAddress"),
                        "serial_number": attrs.get("SerialNumber"),
                        "transceiver_number": txcvr_number,
                        "transceiver_port": transceiver_port,
                        "channel_instance_number": channel_instance_number,
                        "multiplexing_found": multiplexing_found,
                    }
                    
                    for tducer_node in channel_node.get("children", []):
                        if tducer_node.get("tag") == "Transducer":
                            td_attrs = tducer_node.get("attributes", {})
                            # Treat serial number '0' as missing (not a real serial)
                            raw_serial = td_attrs.get("SerialNumber")
                            if raw_serial is not None and str(raw_serial).strip() == '0':
                                raw_serial = None
                            transducer_info[channel_id] = {
                                "serial": raw_serial,
                                "model": td_attrs.get("TransducerName"),
                                "frequency": float(td_attrs.get("Frequency", 0)),
                                "freq_min": float(td_attrs.get("FrequencyMinimum", 0)),
                                "freq_max": float(td_attrs.get("FrequencyMaximum", 0)),
                            }


def _parse_ek80_parameter(param_node, parameter_info):
    """Parse EK80 Parameter XML node to populate operational parameters."""
    for child in param_node.get("children", []):
        if child.get("tag") != "Channel":
            continue
        
        attrs = child.get("attributes", {})
        channel_id = attrs.get("ChannelID")
        if channel_id and channel_id not in parameter_info:
            # Prefer operational values from the Parameter block where present
            # FrequencyStart/FrequencyEnd indicate FM sweep limits used in operation
            freq = float(attrs.get("Frequency", 0))
            freq_start = attrs.get("FrequencyStart")
            freq_end = attrs.get("FrequencyEnd")
            parameter_info[channel_id] = {
                "pulse_form": str(int(attrs.get("PulseForm", 0))),
                "frequency": freq,
                "frequency_start": float(freq_start) if freq_start is not None else None,
                "frequency_end": float(freq_end) if freq_end is not None else None,
                "pulse_length": float(attrs.get("PulseDuration", 0)),
                "transmit_power": float(attrs.get("TransmitPower", 0)),
            }


def _safe_int(value):
    """Safely convert value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _config_sort_key(cfg):
    """Sort key for file configs: by ``metadata_start_time``, earliest first.

    Files whose timestamp is missing or unparseable are placed first (the empty
    string sorts before valid ISO timestamps).
    """
    t = cfg.get("metadata_start_time")
    if t is None:
        return ""  # sort missing timestamps first
    return str(t)


def process_raw_file(raw_path, verbose=True, verify_start_time=False):
    """Scan a single *local* .raw file and return its file configuration.

    This is the per-file unit of :func:`process_raw_folder`, exposed separately
    so callers can drive the iteration themselves — e.g. downloading one remote
    file at a time into local scratch. It only ever reads a local path.

    Args:
        raw_path: Path to a local ``.raw`` file.
        verbose: If True, print per-file progress information.
        verify_start_time: If True, additionally run the full SimradFileReader
            on an EK80 file to obtain its guarded minimum START_TIME.

    Returns:
        dict | None: The file configuration, or ``None`` when the instrument
        type cannot be detected (caller should skip the file).
    """
    # Import here to keep the module-level namespace clean; the reader lives
    # in a sibling sub-package that may not always be available.
    from .simrad_reader.raw_reader import SimradFileReader

    raw_path = Path(raw_path)
    instrument = detect_instrument_type(raw_path)

    if verbose:
        print("=" * 80)
        print(f"File: {raw_path.name}")
        print(f"Instrument (detected): {instrument}")

    if instrument == "UNKNOWN":
        if verbose:
            print("  WARNING: Could not detect instrument type, skipping file")
        return None

    if instrument == "EK80":
        # One pass over headers only; RAW3 sample bodies are skipped.
        scan = scan_ek80_file(raw_path)
        metadata_start_time = scan["metadata_start_time"]

        if verify_start_time:
            # Compare against the reader guarded minimum START_TIME.
            reader = SimradFileReader(instrument)
            reader.process_file(str(raw_path))
            reader_metadata = (
                json.loads(reader.metadata) if reader.metadata else None
            )
            reader_start = (
                reader_metadata.get("START_TIME") if reader_metadata else None
            )
            if reader_start and reader_start != metadata_start_time:
                if verbose:
                    print(
                        f"  WARNING: start time mismatch "
                        f"(scan={metadata_start_time!r}, "
                        f"reader={reader_start!r}); using reader value"
                    )
                metadata_start_time = reader_start
            if reader.errors and verbose:
                _pretty_dict("Read errors:", reader.errors)

        file_config = extract_ek80_file_config(
            raw_path,
            scan["xml_dicts"],
            metadata_start_time,
            timestamps=scan["timestamps"],
            gps_data=scan["gps_data"],
        )
        file_config["file_format"] = "EK80"
        file_config["instrument"] = instrument

        if verbose:
            print("File format: EK80")

    elif instrument == "EK60":
        reader = SimradFileReader(instrument)
        reader.process_file(str(raw_path))

        if verbose:
            print(f"File format (from reader): {reader.file_format}")

        metadata = json.loads(reader.metadata) if reader.metadata else None
        if not metadata and verbose:
            print("Header parameters (FILE_PARAMETERS): <none>")

        if reader.errors and verbose:
            _pretty_dict("Read errors:", reader.errors)

        file_config = extract_ek60_file_config(raw_path, reader, metadata)
        file_config["instrument"] = instrument
    else:
        return None

    if verbose:
        gps = file_config.get("gps_data", {})
        print(f"\n--- GPS Summary ---")
        print(f"  NMEA datagrams found: {gps.get('nmea_count', 0)}")
        print(f"  Valid GPS fixes: {gps.get('valid_gps_count', 0)}")
        if gps.get("first_gps"):
            fg = gps["first_gps"]
            print(f"  First GPS: {fg['latitude']:.6f}, {fg['longitude']:.6f}")

    return file_config


def process_raw_folder(raw_input_folder, verbose=True, verify_start_time=False,
                       raw_files=None):
    """Process all .raw files in a folder and return sorted file configurations.

    Discovers every ``*.raw`` file in *raw_input_folder*, auto‑detects the
    instrument type (EK60 / EK80), extracts channel configurations, GPS data
    and datagram timestamps, then returns the list **sorted by
    ``metadata_start_time``** (earliest first).

    EK80 files are read in a single pass over the datagram headers
    (scan_ek80_file); the large RAW3 sample payloads are never read.
    metadata_start_time is taken from the first datagram, which equals the
    reader START_TIME for files whose datagrams are in chronological order.

    Args:
        raw_input_folder: Path (or str) to the folder containing ``.raw`` files.
        verbose: If True, print progress information for each file.
        verify_start_time: If True, additionally run the full SimradFileReader
            on each EK80 file to obtain its guarded minimum START_TIME and use
            that for metadata_start_time, warning on any mismatch. Slower, and
            only needed when a file may have datagrams out of chronological
            order. EK60 files always use the reader regardless.
        raw_files: Optional pre-resolved list of ``.raw`` file paths to process
            instead of globbing the folder (e.g. a time-window-filtered subset).

    Returns:
        tuple: (file_configs, frequencies_set)
            - file_configs: list of dicts (one per raw file), sorted by
              ``metadata_start_time``.
            - frequencies_set: set of unique frequencies (Hz) found across
              all channels.

    Raises:
        FileNotFoundError: If no ``.raw`` files are found in the folder.
    """
    raw_input_folder = Path(raw_input_folder)
    if raw_files is None:
        raw_files = sorted(raw_input_folder.glob("*.raw"))
    else:
        raw_files = [Path(f) for f in raw_files]

    if not raw_files:
        raise FileNotFoundError(f"No .raw files found in: {raw_input_folder}")

    if verbose:
        print(f"Found {len(raw_files)} raw files in {raw_input_folder}")
        for f in raw_files:
            print(f"  - {f.name}")

    file_configs = []
    frequencies_set = set()

    for raw_path in raw_files:
        file_config = process_raw_file(
            raw_path, verbose=verbose, verify_start_time=verify_start_time
        )
        if file_config is None:
            continue

        file_configs.append(file_config)

        for ch in file_config.get("channels", []):
            if "frequency" in ch:
                frequencies_set.add(ch["frequency"])

    file_configs.sort(key=_config_sort_key)

    if verbose:
        print("\n" + "=" * 80)
        print(f"SUMMARY: Processed {len(file_configs)} files (sorted by metadata_start_time)")
        print(f"Unique frequencies found: {sorted(frequencies_set)} Hz")
        print("=" * 80)

    return file_configs, frequencies_set


def extract_unique_channels(file_configs: list, calibration_date: str) -> dict:
    """
    Extract unique channel configurations from all raw files.

    Args:
        file_configs: List of raw file configuration dicts (as returned by
            extract_ek60_file_config / extract_ek80_file_config).
        calibration_date: User-provided calibration date string used for
            building channel keys.

    Returns:
        Dictionary mapping channel_key -> channel_data (first occurrence).
    """
    from .standardized_file_lib import build_calibration_key

    unique_channels = {}

    for file_config in file_configs:
        for channel in file_config.get('channels', []):
            key = build_calibration_key(channel, calibration_date)
            if key not in unique_channels:
                # Store the first occurrence of this channel configuration
                unique_channels[key] = channel.copy()

    return unique_channels


