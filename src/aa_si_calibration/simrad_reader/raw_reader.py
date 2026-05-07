# -*- coding: utf-8 -*-

r"""
Reader class for Simrad .raw files created by EK/ES60/ES70, ME70 and EK80 instruments.
Classes _SimradDatagramParser and SimradConfigParser modified and adapted from
the echolab module created by Zac Berkowitz <zachary.berkowitz@noaa.gov>
National Oceanic and Atmospheric Administration Alaska Fisheries Science Center
Midwater Assesment and Conservation Engineering Group.

Created by Chuck Anderson <charles.anderson@noaa.gov>
NOAA National Centers for Environmental Information

revised April 2020, Veronica Martinez <veronica.martinez@noaa.gov>
NOAA National Centers for Environmental Information
"""

import os
import sys
import hashlib
import pytz
from datetime import datetime,timedelta
from struct import unpack, calcsize
from lxml import etree as ET

from .base_reader import BaseReader
from .reader_errors import FileTypeError

# Create parser instance with external entity resolution disabled for security.
parser = ET.XMLParser(resolve_entities=False, recover=True)


class SimradFileReader(BaseReader):
    def __init__(self, instrument):
        super(SimradFileReader, self).__init__()  #initialize this subclass
        self.type = ''

        self.instrument = instrument
        self.soundSpeed = 0.0
        self.sampleInterval = 0.0
        self.transducerDepth = 0.0
        self.gpgga = []
        self.gpgll = []
        self.gprmc = []
        self.ingga = []
        self.ingll = []
        self.inrmc = []
        self.inggk = []
        self.channels = {}
        self.config_datagrams = {}
        self.config = {}
        self.file_format = None
        self.dg_size = None
        self.current_time = None
        self.total_nav = 0
        self.bad_nav = 0

    def check_file(self, fid):
        """Check if this is a Simrad .raw file.

        Compare instrument type and initial datagram type to verify the file
        format. If valid, set self.file_format.

        Args:
            fid(obj): The file object.

        Returns(str): Error if it's not a valid file.

        """
        # Read size and type of the first datagram. First datagram should be
        # XML0 for EK80 format data and CON0 for other Simrad files.

        dg_size, dg_type = unpack('=I4s', fid.read(8))

        if dg_type == b'XML0' and self.instrument == 'EK80':
            fid.seek(0)   # rewind to the beginning of file
            self.file_format = 'EK80'
            return fid
        elif dg_type == b'XML0' and self.instrument == 'ES80':
            fid.seek(0)   # rewind to the beginning of file
            self.file_format = 'EK80'
            return fid
        elif dg_type == b'XML0' and self.instrument == 'WBT':
            fid.seek(0)   # rewind to the beginning of file
            self.file_format = 'EK80'
            return fid
        elif dg_type == b'XML0' and self.instrument == 'EK60':
            fid.seek(0)
            self.file_format = 'EK60_EK80'
            return fid
        elif dg_type == b'CON0' and self.instrument == 'EK60':
            fid.seek(0)
            self.file_format = 'EK60'
            return fid
        elif dg_type == b'CON0' and self.instrument == 'ES60':
            fid.seek(0)
            self.file_format = 'ES60'
            return fid
        elif dg_type == b'CON0' and self.instrument == 'ES70':
            fid.seek(0)
            self.file_format = 'ES70'
            return fid

        #*********************
        elif dg_type == b'XML0' and self.instrument == 'ME70':
            fid.seek(dg_size, os.SEEK_CUR)
            dg_size, dg_type = unpack('=I4s', fid.read(8))
            fid.seek(dg_size, os.SEEK_CUR)
            dg_size, dg_type = unpack('=I4s', fid.read(8))
            if dg_type == b'CON1':
                fid.seek(0)
                self.file_format = 'ME70'
                return fid
            else:
                fid.close()
                self.errors.append(
                    f'{FileTypeError(self.filename, self.instrument)}')
        #********************

        elif dg_type == b'CON0' and self.instrument == 'ME70':
            fid.seek(dg_size, os.SEEK_CUR)
            dg_size, dg_type = unpack('=I4s', fid.read(8))
            if dg_type == b'CON1':
                fid.seek(0)
                self.file_format = 'ME70'
                return fid
            else:
                fid.close()
                self.errors.append(
                    f'{FileTypeError(self.filename, self.instrument)}')

        elif dg_type == b'CON0' and self.instrument == 'MS70':
            fid.seek(dg_size, os.SEEK_CUR)
            dg_size, dg_type = unpack('=I4s', fid.read(8))
            if dg_type == b'CON1':
                fid.seek(0)
                self.file_format = 'ME70'
                return fid
            else:
                fid.close()
                self.errors.append(
                    f'{FileTypeError(self.filename, self.instrument)}')
        else:
            fid.close()
            self.errors.append(
                            f'{FileTypeError(self.filename, self.instrument)}')

    def process_file(self, file_path, check_only=False):
        """Main  method for processing file.

        Args:
            file_path(str): Full path to file to process.
            check_only(bool): Control whether file is processed or just
            check to make sure it's a valid file.
        """

        # Starting point for process method in instrument specific reader.
        self.file_path = file_path
        self.filename = os.path.basename(file_path)
        fid = open(file_path, 'rb')

        # check if file is valid.
        fid = self.check_file(fid)
        if check_only:
            # print(f' Valid {self.file_format} .raw file: {self.filename}')
            return True, self.file_format

        # Initialize checksum hash.
        hashalg = getattr(hashlib, 'md5')()

        # Dictionary of handled datagrams and list of keys
        dg_parsers = {
            b'XML0': self.xml_parser,   # EK80 format specific. Also new ME70 format
            b'NME0': self.nmea_parser,  # EK60/ES60/ES70/ME70 format specific
            b'RAW3': self.range_calc_RAW3,  # EK80 format specific
            b'RAW0': self.range_calc_RAW0,  # EK60/ES60/ES70/ME70 format
            b'CON': self.con_parser  # EK60/ES60/ES70/ME70 format specific
        }
        dg_types = dg_parsers.keys()

        # Loop through datagrams.
        while True:
            # Read the datagram from datagram header.
            # Process datagram time stamp to update time extent of file.
            # Process datagram if of interest or skip datagram if not.
            try:
                header = fid.read(16)
                dg_common = unpack('=I4sQ', header)
                self.dg_size = dg_common[0]
                dg_type = dg_common[1]
            except Exception as e:
                if str(e) == 'unpack requires a buffer of 16 bytes':
                    # End of file has been reached
                    #raise readerEOF  #TODO: raise or break??
                    break
                else:
                    # print('error')
                    self.errors.append('Error parsing datagram header')
                    break

            # Get timestamp, convert to datetime, update start & end times
            try:
                self.current_time = None
                self.current_time = self.time_convert(dg_common[2])
                if self.start_time is None and self.end_time is None:
                    self.start_time = self.current_time
                    self.end_time = self.current_time
                elif (datetime(1970, 1, 1, 0, 0, 1, 0, pytz.UTC) <
                      self.current_time < self.start_time):
                    self.start_time = self.current_time
                elif self.current_time > self.end_time:
                    self.end_time = self.current_time
            except Exception as e:
                self.errors.append('Error parsing timestamp in datagram header')
                break

            try:
                # Read the rest of the datagram
                if self.file_format == 'EK60' or \
                        (self.file_format == 'ME70' and dg_type != b'XML0')\
                        or \
                        self.file_format == 'ES60' or self.file_format == 'ES70':
                    fid.seek(-12, os.SEEK_CUR)
                    dg_body = fid.read(self.dg_size+4)
                else:
                    dg_body = fid.read(self.dg_size-8)
            except ValueError as e:
                self.errors.append("Error reading datagram. Read length didn't match expected value")
                break

            # If datagram type is of interest, process with appropriate method,
            # otherwise move file pointer to end of datagram
            try:
                if dg_type in dg_types:
                    dg_parsers[dg_type](dg_body)
                elif dg_type[:-1] in dg_types:
                    # Process both the con0, and if it's ME70, the con1 datagrams.
                    dg_parsers[dg_type[:-1]](dg_type, dg_body)
            except Exception as e:
                self.errors.append(str(e))
                break

            hashalg.update(header)
            hashalg.update(dg_body)
        self.checksum = hashalg.hexdigest()
        self.finalize_data()
        self.get_metadata()
        if fid:
            fid.close()

    def xml_parser(self, data):
        """
        Read XML0 datagrams from EK80 format files to parse out raw XML text.
        Then call appropriate parser to pull needed information.

            Args:
                data(bytes): Record datagram body in bytes
        """

        read_length = self.dg_size-12
        unpack_string = str(read_length)+'s'
        raw_xml = unpack(unpack_string, data[0:read_length])[0]
        # unpack_string = str(read_length-12)+'s'
        # raw_xml = unpack(unpack_string, data[12:read_length])[0]
        # print(raw_xml)
        try:
            root = ET.fromstring(raw_xml, parser=parser)
        except Exception as e:
            # print('XML read error')
            # print(e)
            self.errors.append(f'Error parsing XML datagram')
            return
        # Set up channels dictionary and populate frequencies with transducers
        # base frequency. If used in wide beam, range expanded by parameter
        # datagrams
        if root.tag == 'Configuration':
            # Find the index of the transceiver root element.
            for index, element in enumerate(root):
                if element.tag == 'Transceivers':
                    break

            for transceiver in root[index]:
                for channel in transceiver[0]:
                    channel_id = channel.get('ChannelID')
                    # added float() for cases when input is a string float and int cannot automatically convert
                    min_frequency = int(float(channel[0].get('Frequency')))
                    max_frequency = int(float(channel[0].get('Frequency')))
                    # beam_type = int(channel[0].get('BeamType'))
                    #TODO: hard coded beamType to Split
                    self.channels[channel_id] = {'minFrequency': min_frequency,
                             'maxFrequency': max_frequency, 'beamType': 'Split'}

        # Get sound speed value for use in range calculation.
        elif root.tag == 'Environment':
            try:
                self.soundSpeed = float(root.get('SoundSpeed'))
            except TypeError:
                self.soundSpeed = 1500  # global average

        # Process parameter information. Update frequency ranges and get sample
        # interval and transducer depth for range calculation on next sample
        # datagram
        elif root.tag == 'Parameter':
            # print(raw_xml)
            channel_id = root[0].get('ChannelID')

            if 'FrequencyStart' in str(raw_xml):
                # added float() for cases when input is a string float and int cannot automatically convert
                min_frequency = int(int(float(root[0].get('FrequencyStart')))/1000)
                max_frequency = int(int(float(root[0].get('FrequencyEnd')))/1000)
                # check for wideband
                if min_frequency != max_frequency:
                    frequency = ''
                    self.channels[channel_id]['beamType'] = 'Wide Band'

                    # Add WkHz units to wideband frequencies
                    if min_frequency < 18 < max_frequency:
                        frequency = '18WkHz'
                    elif min_frequency < 38 < max_frequency:
                        frequency = '38WkHz'
                    elif min_frequency < 60 < max_frequency:
                        frequency = '60WkHz'
                    elif min_frequency < 65 <= max_frequency:
                        frequency = '65WkHz'
                    elif min_frequency < 70 < max_frequency:
                        frequency = '70WkHz'
                    elif min_frequency < 110 < max_frequency:
                        frequency = '110WkHz'
                    elif min_frequency < 120 < max_frequency:
                        frequency = '120WkHz'
                    elif min_frequency < 155 < max_frequency:
                        frequency = '155WkHz'
                    elif min_frequency < 200 < max_frequency:
                        frequency = '200WkHz'
                    elif min_frequency < 240 < max_frequency:
                        frequency = '240WkHz'
                    elif min_frequency < 333 < max_frequency:
                        frequency = '333WkHz'
                    elif min_frequency < 710 < max_frequency:
                        frequency = '710WkHz'
                    else:
                        self.errors.append(f"Frequencies {min_frequency} - "
                                           f"{max_frequency} out of range")
                else:
                    frequency = str(min_frequency)
                if frequency:
                    self.frequencies.add(frequency)
            else:
                # added float() for cases when input is a string float and int cannot automatically convert
                min_frequency = int(int(float(root[0].get('Frequency')))/1000)
                max_frequency = int(int(float(root[0].get('Frequency')))/1000)
                self.frequencies.update([str(min_frequency),
                                         str(max_frequency)])

            if min_frequency < self.channels[channel_id]['minFrequency']:
                self.channels[channel_id]['minFrequency'] = min_frequency
            if max_frequency > self.channels[channel_id]['maxFrequency']:
                self.channels[channel_id]['maxFrequency'] = max_frequency

            self.sampleInterval = float(root[0].get('SampleInterval'))

            try:
                self.transducerDepth = float(root[0].get('TransducerDepth'))
            except Exception:
                self.transducerDepth = 0

    def nmea_parser(self, data):
        """
        Read NMEA string from NMEA datagram and append to list based on
        string type

            Args:
                data(bytes): Record datagram body in bytes
        """

        read_length = self.dg_size-12
        unpack_string = str(read_length)+'s'
        rawNMEA = str(unpack(unpack_string, data[:read_length])[0])

        if rawNMEA.count('GPGGA'):
            self.gpgga.append(rawNMEA)
        elif rawNMEA.count('GPGLL'):
            self.gpgll.append(rawNMEA)
        elif rawNMEA.count('GPRMC'):
            self.gprmc.append(rawNMEA)
        elif rawNMEA.count('INGGA'):
            self.ingga.append(rawNMEA)
        elif rawNMEA.count('INGGK'):
            self.inggk.append(rawNMEA)
        elif rawNMEA.count('INGLL'):
            self.ingll.append(rawNMEA)
        elif rawNMEA.count('INRMC'):
            self.inrmc.append(rawNMEA)

    def process_nav(self):
        """
        Process nav NMEA strings to extract lon and lat values
        """

        def calc_decimal_degrees(x, control='lat'):
            """
            Convert position in dd.mm(hundredths) to decimal degree
            """
            d, m_ = str(x).split('.')
            if control == 'lon':
                if len(d) != 5 or int(d[:3]) > 180 or int(d[3:]) > 59:
                    # Improperly formatted lon value
                    self.bad_nav += 1
                    return None
                m = d[3:] + '.' + m_
                dd = float(d[:3]) + float(m) / 60
            else:
                if len(d) != 4 or int(d[:2]) > 90 or int(d[2:]) > 59:
                    # Improperly formatted lat value
                    self.bad_nav += 1
                    return None
                m = d[2:] + '.' + m_
                dd = float(d[:2]) + float(m) / 60
            return dd

        # Start with GPGGA and if not present, work down list ordered by probable quality
        nmea_strs = [self.gpgga, self.gpgll, self.gprmc, self.ingga, self.inggk, self.ingll, self.inrmc]
        for strings in nmea_strs:
            self.total_nav = len(strings)
            self.bad_nav = 0
            for string in strings:

                currentLat = -99.0
                currentLon = -999.0
                timestamp = ''

                try:
                    parts = string.split(',')
                    if "GPGGA" in parts[0] or "INGGA" in parts[0]:
                        time = str(parts[1])
                        # date not found in nmea string. Use date from current_time
                        date = datetime.date(self.current_time).strftime('%Y-%m-%d')
                        nmea_timestamp = f"{date} {time}"
                    elif "GPGLL" in parts[0] or "INGLL" in parts[0]:
                        time = str(parts[5])
                        # date not found in nmea string. Use date from current_time
                        date = datetime.date(self.current_time).strftime('%Y-%m-%d')
                        nmea_timestamp = f"{date} {time}"
                    if "GPRMC" in parts[0] or "INRMC" in parts[0]:
                        #TODO: Need to test this to check if date format is correct
                        # TODO: Is this meant to be a new if statement? Can both occur at once?
                        time = str(parts[1])  # (hhmmss.ss format)
                        date = datetime.date(str(parts[9])).strftime('%Y-%m-%d')  # (ddmmyy format)
                        nmea_timestamp = f"{date} {time}"
                    elif "INGGK" in parts[0]:
                        time = str(parts[1])
                        date = datetime.date(self.current_time).strftime('%Y-%m-%d')  # (ddmmyy format)
                        nmea_timestamp = f"{date} {time}"

                    try:
                        timestamp = datetime.strptime(nmea_timestamp, "%Y-%m-%d %H%M%S.%f")
                    except ValueError:
                        timestamp = datetime.strptime(nmea_timestamp, "%Y-%m-%d %H%M%S")

                    # Get latitude and longitude hemisphere designators then
                    # convert to decimal degrees. W lon and S lat are converted
                    # to negative numbers

                    # if 'N'in parts or 'S'in parts process lat
                    try:
                        latIndex = parts.index('N') - 1
                        rawLat = parts[latIndex]
                        currentLat = calc_decimal_degrees(rawLat, 'lat')
                    except:
                        latIndex = parts.index('S') - 1
                        rawLat = parts[latIndex]
                        currentLat = calc_decimal_degrees(rawLat, 'lat') * -1

                    # if 'E'in parts or 'W'in parts process lon
                    try:
                        lonIndex = parts.index('W') - 1
                        rawLon = parts[lonIndex]
                        currentLon = calc_decimal_degrees(rawLon, 'lon') * -1
                    except:
                        lonIndex = parts.index('E') - 1
                        rawLon = parts[lonIndex]
                        currentLon = calc_decimal_degrees(rawLon, 'lon')

                    self.raw_nav.append((timestamp, round(currentLon, 5),
                                             round(currentLat, 5)))

                except Exception:
                    # Silently skip over bad string
                    self.bad_nav += 1
                    pass

            if len(self.raw_nav) > 2:
                return

    def range_calc_RAW3(self, data):
        """
        Calculate recording range value for datagram by reading number of
        samples from RAW3 sample datagram and multiplying by sample interval
        and sound speed

            Args:
                data(bytes): Record datagram body in bytes
        """

        # read sample count. calculate range for datagram and add to ranges list
        try:
            sampleCount = unpack('=I', data[136:140])[0]
            meters_per_sample = self.soundSpeed / 2.0 * self.sampleInterval
            maxDepth = self.transducerDepth + (sampleCount * meters_per_sample)
            maxDepth = int(round(maxDepth))
            if maxDepth > self.recording_range:
                self.recording_range = maxDepth
        except Exception as e:
            self.errors.append('Error calculating recording range from RAW3 sample datagram')

    def range_calc_RAW0(self, data):
        """
        Calculate recording range value for channel by reading count,
        sound_velocity, sample_interval, and transducer_depth from RAW0
        sample datagram.

            Args:
                data(bytes): Record datagram body in bytes
        """

        # move ahead to sample transducer depth location and read depth.
        self.transducerDepth = unpack('f', data[16:20])[0]
        
        # Extract frequency, transmit_power, pulse_length from RAW0
        frequency = unpack('f', data[20:24])[0]
        transmit_power = unpack('f', data[24:28])[0]
        pulse_length = unpack('f', data[28:32])[0]
        
        # Store per-frequency operational parameters (first RAW0 per frequency only)
        # Key by frequency (Hz) since RAW0 channel numbers don't match CON0 transceiver numbers
        freq_key = int(frequency)
        if freq_key not in self.channels:
            self.channels[freq_key] = {
                'frequency': frequency,
                'transmit_power': transmit_power,
                'pulse_length': pulse_length,
            }
        
        # Store file-level values from first RAW0 encountered
        if self.power is None:
            self.power = transmit_power
        if self.pulse_length is None:
            self.pulse_length = pulse_length

        # move ahead to sample interval and sound velocity and read both
        self.sampleInterval, self.soundSpeed = unpack('ff', data[36:44])

        # Move ahead to sample count and read count
        count = unpack('=l', data[80:84])[0]

        # calculate recording range for datagram and add to range list
        meters_per_sample = self.soundSpeed / 2.0 * self.sampleInterval
        maxDepth = self.transducerDepth + (count * meters_per_sample)
        maxDepth = int(round(maxDepth))
        if maxDepth > self.recording_range:
            self.recording_range = maxDepth
            

    @staticmethod
    def time_convert(dt):
        """
        Convert raw timestamp from datagrams to python datetime format

            Args
                dt(str) = raw timestamp string
        """
        microseconds = dt / 10
        seconds, microseconds = divmod(microseconds, 1000000)
        days, seconds = divmod(seconds, 86400)
        timestamp = datetime(1601, 1, 1, 0, 0, 0, 0, pytz.UTC)+timedelta(days, seconds, microseconds)

        return timestamp

    def con_parser(self, dg_type, data):
        """
        Parse CON0, and if ME70 data, CON1 datagrams. This method leverages the
        SimradDatagramParser and SimradConfigParser classes created by Zac
        Berkowitz NMFS>AFSC

            Args:
                data(bytes): Record datagram body in bytes
                dg_type(str): Datagram type
        """

        raw_dgram = data[:self.dg_size]

        # Parse configuration datagram and add to config datagram dictionary
        config_datagram = SimradConfigParser(self.errors).from_string(raw_dgram)
        self.config_datagrams[dg_type] = config_datagram

    def finalize_data(self):
        """
        Finalize file information for return to base_reader.py
        """
        # Process navigation points
        self.process_nav()

        # Calculate percentage of bad navigation points and check against threshold
        if self.bad_nav and (self.bad_nav/self.total_nav) > 0.50:
            self.errors.append('Bad navigation due to improperly formatted lon or lat values')

        if self.file_format != 'EK80' and self.file_format != 'EK60_EK80':
            # process configuration datagrams into config block
            # All files must have a valid CON0 datagram
            if b'CON0' in self.config_datagrams:
                con0_datagram = self.config_datagrams[b'CON0']
                sounder_name = con0_datagram['sounder_name']

                # populate self.config
                config_fields = ['sounder_name', 'transceivers']
                if self.config == {}:
                    for field in config_fields:
                        self.config[field] = con0_datagram[field]

                # Get beam type, 0 = Single, 1 = Split)
                for transceiver in self.config['transceivers']:
                    beam_type = (self.config['transceivers'][transceiver]['beam_type'])
                    if beam_type == 1:
                        self.type = 'Split'
                    elif beam_type == 0:
                        self.type = 'Single'
                    else:
                        self.errors.append(f'Expected beam type of 1 or 0. Got '
                                           f'{beam_type}')

                if (sounder_name == 'MBES' or sounder_name == 'ME70' or
                        sounder_name == 'MBS' or sounder_name == "MS70"):
                    self.type = 'Multibeam'
                    try:
                        con1_datagram = self.config_datagrams[b'CON1']
                        self.config['beam_config'] = con1_datagram.get(
                            'beam_config', '')
                    except KeyError:
                        self.errors.append('ME70 (MBES) data but no CON1 datagram '
                                           'found. No beam config available')

                    # Get beam count
                    try:
                        parser = ET.XMLParser(resolve_entities=False)
                        beam_config = ET.fromstring(self.config['beam_config'], parser=parser)
                    except ET.XMLSyntaxError as e:
                        if 'Document is empty, line 1, column 1' in str(e):
                            # beam type is empty
                            beam_config = None
                        else:
                            # string might have incorrect utf label for it's content. specify utf8
                            parser = ET.XMLParser(encoding='utf8')
                            beam_config = ET.fromstring(self.config['beam_config'], parser=parser)
                    try:
                        self.number_beams = int(beam_config.find(".//*["
                                                "@name='NoOfBeamsInFan']").get('value'))
                    except AttributeError:
                        # Nonetype object returned.
                        # Check the <Fan> element in the new ME70 format to retrieve the NoOfBeamsInFan attribute
                        try:
                            self.number_beams = int(beam_config.find(".//Fan").get('NoOfBeamsInFan'))
                        except AttributeError:
                            # <Fan> element not found
                            self.number_beams = None

                    # Get swath
                    for transceiver in self.config['transceivers']:
                        for item in self.config['transceivers'][transceiver]:
                            if item == 'beamwidth_athwartship':
                                self.swath = self.swath+(self.config[
                                    'transceivers'][transceiver][item])

                # Get frequencies from config datagram
                for transceiver in self.config['transceivers']:
                    self.frequencies.add(int(self.config['transceivers'][
                                                 transceiver]['frequency'] / 1000))
            else:
                self.errors.append('No CON0 datagram found.')

        elif self.file_format == 'EK80' or self.file_format == 'EK60_EK80':
            self.type = set()
            for channel in self.channels:
                beam_type = self.channels[channel]['beamType']
                self.type.add(beam_type)
            # convert set to comma separated string
            self.type = ', '.join(str(s) for s in self.type)

        # round range to nearest 5 meter increment
        #TODO: How should recording range be rounded? Should 259 be 260 or 250?
        #test EK60 files for example
        self.recording_range = (int(self.recording_range/5)*5)
        # round swath
        self.swath = int(self.swath)
        # process frequencies into formats needed for database metadata
        self.process_frequencies()


# Zac's Code
class _SimradDatagramParser(object):
    """
    """

    def __init__(self, header_type, header_formats):
        self._id = header_type
        self._headers = header_formats
        self._versions    = header_formats.keys()

    def header_fmt(self, version=0):
        return '=' + ''.join([x[1] for x in self._headers[version]])

    def header_size(self, version=0):
        return calcsize(self.header_fmt(version))

    def header_fields(self, version=0):
        return [x[0] for x in self._headers[version]]

    def header(self, version=0):
        return self._headers[version][:]

    def validate_data_header(self, data):

        if isinstance(data, dict):
            type_ = data['type'][:3]
            version = data['type'][3:4]

        #TODO: changed to bytes from string
        elif isinstance(data, bytes):
            type_ = data[:3].decode()
            version = data[3:4]

        else:
            raise TypeError('Expected a dict or str')

        if type_ != self._id:
            raise ValueError('Expected data of type %s, not %s' %(self._id, type_))

        if version not in self._versions:
            raise ValueError('No parser available for type %s version %s' %(self._id, version))

        return type_, version

    def from_string(self, raw_string):

        id_, version = self.validate_data_header(raw_string)
        return self._unpack_contents(raw_string, version=version)


# Zac's code
class SimradConfigParser(_SimradDatagramParser):
    """
    Simrad Configuration Datagram parser operates on dictonaries with the following keys:

        type:         string == 'CON0'
        low_date:     long uint representing LSBytes of 64bit NT date
        high_date:    long uint representing MSBytes of 64bit NT date
        timestamp:    datetime.datetime object of NT date, assumed to be UTC

        survey_name                     [str]
        transect_name                   [str]
        sounder_name                    [str]
        version                         [str]
        spare0                          [str]
        transceiver_count               [long]
        transceivers                    [list] List of dicts representing Transducer Configs:

        ME70 Data contains the following additional values (data contained w/in first 14
            bytes of the spare0 field)

        multiplexing                    [short]  Always 0
        time_bias                       [long] difference between UTC and local time in min.
        sound_velocity_avg              [float] [m/s]
        sound_velocity_transducer       [float] [m/s]
        beam_config                     [str] Raw XML string containing beam config. info


    Transducer Config Keys (ER60/ES60/ES70 sounders):
        channel_id                      [str]   channel ident string
        beam_type                       [long]  Type of channel (0 = Single, 1 = Split)
        frequency                       [float] channel frequency
        equivalent_beam_angle           [float] dB
        beamwidth_alongship             [float]
        beamwidth_athwartship           [float]
        angle_sensitivity_alongship     [float]
        angle_sensitivity_athwartship   [float]
        angle_offset_alongship          [float]
        angle_offset_athwartship        [float]
        pos_x                           [float]
        pos_y                           [float]
        pos_z                           [float]
        dir_x                           [float]
        dir_y                           [float]
        dir_z                           [float]
        pulse_length_table              [float[5]]
        spare1                          [str]
        gain_table                      [float[5]]
        spare2                          [str]
        sa_correction_table             [float[5]]
        spare3                          [str]
        gpt_software_version            [str]
        spare4                          [str]

    Transducer Config Keys (ME70 sounders):
        channel_id                      [str]   channel ident string
        beam_type                       [long]  Type of channel (0 = Single, 1 = Split)
        reserved1                       [float] channel frequency
        equivalent_beam_angle           [float] dB
        beamwidth_alongship             [float]
        beamwidth_athwartship           [float]
        angle_sensitivity_alongship     [float]
        angle_sensitivity_athwartship   [float]
        angle_offset_alongship          [float]
        angle_offset_athwartship        [float]
        pos_x                           [float]
        pos_y                           [float]
        pos_z                           [float]
        beam_steering_angle_alongship   [float]
        beam_steering_angle_athwartship [float]
        beam_steering_angle_unused      [float]
        pulse_length                    [float]
        reserved2                       [float]
        spare1                          [str]
        gain                            [float]
        reserved3                       [float]
        spare2                          [str]
        sa_correction                   [float]
        reserved4                       [float]
        spare3                          [str]
        gpt_software_version            [str]
        spare4                          [str]

    from_string(str):   parse a raw config datagram
                        (with leading/trailing datagram size stripped)

    """

    def __init__(self, errors):
        self.errors = errors
        headers = {b'0':[('type', '4s'),
                      ('low_date', 'L'),
                      ('high_date', 'L'),
                      ('survey_name', '128s'),
                      ('transect_name', '128s'),
                      ('sounder_name', '128s'),
                      ('version', '30s'),
                      ('spare0', '98s'),
                      ('transceiver_count', 'l')
                      ],
                   b'1':[('type', '4s'),
                      ('low_date', 'L'),
                      ('high_date', 'L')
                      ]}

        _SimradDatagramParser.__init__(self, 'CON', headers)

        self._transducer_headers = {'ER60': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('gain', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship', 'f'),
                                             ('angle_sensitivity_athwartship', 'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('dir_x', 'f'),
                                             ('dir_y', 'f'),
                                             ('dir_z', 'f'),
                                             ('pulse_length_table', '5f'),
                                             ('spare1', '8s'),
                                             ('gain_table', '5f'),
                                             ('spare2', '8s'),
                                             ('sa_correction_table', '5f'),
                                             ('spare3', '8s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ],
                                    'ES60': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('gain', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship', 'f'),
                                             ('angle_sensitivity_athwartship', 'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('dir_x', 'f'),
                                             ('dir_y', 'f'),
                                             ('dir_z', 'f'),
                                             ('pulse_length_table', '5f'),
                                             ('spare1', '8s'),
                                             ('gain_table', '5f'),
                                             ('spare2', '8s'),
                                             ('sa_correction_table', '5f'),
                                             ('spare3', '8s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ],
                                    'ES70': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('gain', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship', 'f'),
                                             ('angle_sensitivity_athwartship', 'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('dir_x', 'f'),
                                             ('dir_y', 'f'),
                                             ('dir_z', 'f'),
                                             ('pulse_length_table', '5f'),
                                             ('spare1', '8s'),
                                             ('gain_table', '5f'),
                                             ('spare2', '8s'),
                                             ('sa_correction_table', '5f'),
                                             ('spare3', '8s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ],
                                    'MBES': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('reserved1', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship', 'f'),
                                             ('angle_sensitivity_athwartship', 'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('beam_steering_angle_alongship', 'f'),
                                             ('beam_steering_angle_athwartship', 'f'),
                                             ('beam_steering_angle_unused', 'f'),
                                             ('pulse_length', 'f'),
                                             ('reserved2', 'f'),
                                             ('spare1', '20s'),
                                             ('gain', 'f'),
                                             ('reserved3', 'f'),
                                             ('spare2', '20s'),
                                             ('sa_correction', 'f'),
                                             ('reserved4', 'f'),
                                             ('spare3', '20s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ],
                                    'MBS': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('reserved1', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship',
                                              'f'),
                                             ('angle_sensitivity_athwartship',
                                              'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('beam_steering_angle_alongship',
                                              'f'),
                                             ('beam_steering_angle_athwartship',
                                              'f'),
                                             (
                                             'beam_steering_angle_unused', 'f'),
                                             ('pulse_length', 'f'),
                                             ('reserved2', 'f'),
                                             ('spare1', '20s'),
                                             ('gain', 'f'),
                                             ('reserved3', 'f'),
                                             ('spare2', '20s'),
                                             ('sa_correction', 'f'),
                                             ('reserved4', 'f'),
                                             ('spare3', '20s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ],
                                    'MS70': [
                                            ('channel_id', '128s'),
                                            ('beam_type', 'l'),
                                            ('frequency', 'f'),
                                            ('reserved1', 'f'),
                                            ('equivalent_beam_angle', 'f'),
                                            ('beamwidth_alongship', 'f'),
                                            ('beamwidth_athwartship', 'f'),
                                            ('angle_sensitivity_alongship',
                                             'f'),
                                            ('angle_sensitivity_athwartship',
                                             'f'),
                                            ('angle_offset_alongship', 'f'),
                                            ('angle_offset_athwartship', 'f'),
                                            ('pos_x', 'f'),
                                            ('pos_y', 'f'),
                                            ('pos_z', 'f'),
                                            ('beam_steering_angle_alongship',
                                             'f'),
                                            ('beam_steering_angle_athwartship',
                                             'f'),
                                            (
                                                'beam_steering_angle_unused', 'f'),
                                            ('pulse_length', 'f'),
                                            ('reserved2', 'f'),
                                            ('spare1', '20s'),
                                            ('gain', 'f'),
                                            ('reserved3', 'f'),
                                            ('spare2', '20s'),
                                            ('sa_correction', 'f'),
                                            ('reserved4', 'f'),
                                            ('spare3', '20s'),
                                            ('gpt_software_version', '16s'),
                                            ('spare4', '28s')
                                            ],
                                    'ME70': [('channel_id', '128s'),
                                             ('beam_type', 'l'),
                                             ('frequency', 'f'),
                                             ('reserved1', 'f'),
                                             ('equivalent_beam_angle', 'f'),
                                             ('beamwidth_alongship', 'f'),
                                             ('beamwidth_athwartship', 'f'),
                                             ('angle_sensitivity_alongship', 'f'),
                                             ('angle_sensitivity_athwartship', 'f'),
                                             ('angle_offset_alongship', 'f'),
                                             ('angle_offset_athwartship', 'f'),
                                             ('pos_x', 'f'),
                                             ('pos_y', 'f'),
                                             ('pos_z', 'f'),
                                             ('beam_steering_angle_alongship', 'f'),
                                             ('beam_steering_angle_athwartship', 'f'),
                                             ('beam_steering_angle_unused', 'f'),
                                             ('pulse_length', 'f'),
                                             ('reserved2', 'f'),
                                             ('spare1', '20s'),
                                             ('gain', 'f'),
                                             ('reserved3', 'f'),
                                             ('spare2', '20s'),
                                             ('sa_correction', 'f'),
                                             ('reserved4', 'f'),
                                             ('spare3', '20s'),
                                             ('gpt_software_version', '16s'),
                                             ('spare4', '28s')
                                             ]
                                    }

    def _unpack_contents(self, raw_string, version):

        data = {}
        round6 = lambda x: round(x, ndigits=6)
        header_values = unpack(self.header_fmt(version), raw_string[:self.header_size(version)])

        for indx, field in enumerate(self.header_fields(version)):
            data[field] = header_values[indx]

            #TODO: Added this from Rick's code. eliminates need to add 'b'
            # in front of .strip('\x00') below
            #  handle Python 3 strings
            if isinstance(data[field], bytes):
                data[field] = data[field].decode('latin_1')
            #**************************************************

       # data['timestamp'] = self.nt_to_unix(data['low_date'], data['high_date'])

        if version == b'0':

            data['transceivers'] = {}

            for field in ['transect_name', 'version', 'survey_name', 'sounder_name']:
                data[field] = data[field].strip('\x00')

            sounder_name = data['sounder_name']
            if sounder_name == 'MBES' or sounder_name == 'ME70':
                _me70_extra_values = unpack('=hLff', data['spare0'].encode()[
                :14])
                data['multiplexing'] = _me70_extra_values[0]
                data['time_bias'] = _me70_extra_values[1]
                data['sound_velocity_avg'] = _me70_extra_values[2]
                data['sound_velocity_transducer'] = _me70_extra_values[3]
                data['spare0'] = data['spare0'][:14] + data['spare0'][14:].strip('\x00')

            else:
                data['spare0'] = data['spare0'].strip('\x00')

            buf_indx = self.header_size(version)

            try:
                transducer_header = self._transducer_headers[sounder_name]
                _sounder_name_used = sounder_name
            except KeyError:
                self.errors.append(f'Unknown sounder_name:  {sounder_name}, '
                                   f'(not one of '
                                   f'{self._transducer_headers.keys()}. '
                                   f'Will use ER60 transducer config fields '
                                   f'as default')

                transducer_header = self._transducer_headers['ER60']
                _sounder_name_used = 'ER60'

            txcvr_header_fields = [x[0] for x in transducer_header]
            txcvr_header_fmt    = '=' + ''.join([x[1] for x in transducer_header])
            txcvr_header_size   = calcsize(txcvr_header_fmt)

            for txcvr_indx in range(1, data['transceiver_count'] + 1):
                txcvr_header_values = unpack(txcvr_header_fmt, raw_string[buf_indx:buf_indx + txcvr_header_size])
                txcvr = data['transceivers'].setdefault(txcvr_indx, {})

                if _sounder_name_used in ['ER60', 'ES60', 'ES70']:
                    for txcvr_field_indx, field in enumerate(txcvr_header_fields[:17]):
                       txcvr[field] = txcvr_header_values[txcvr_field_indx]

                  #  txcvr['pulse_length_table']   = np.fromiter(map(round6, txcvr_header_values[17:22]), 'float')
                    txcvr['spare1']               = txcvr_header_values[22]
                 #   txcvr['gain_table']           = np.fromiter(map(round6, txcvr_header_values[23:28]), 'float')
                    txcvr['spare2']               = txcvr_header_values[28]
                  #  txcvr['sa_correction_table']  = np.fromiter(map(round6, txcvr_header_values[29:34]), 'float')
                    txcvr['spare3']               = txcvr_header_values[34]
                    txcvr['gpt_software_version'] = txcvr_header_values[35]
                    txcvr['spare4']               = txcvr_header_values[36]

                elif _sounder_name_used  == 'MBES' or _sounder_name_used  == \
                        'ME70' or _sounder_name_used == 'MBS' or _sounder_name_used == "MS70":
                    for txcvr_field_indx, field in enumerate(txcvr_header_fields):
                        txcvr[field] = txcvr_header_values[txcvr_field_indx]

                else:
                    raise RuntimeError('Unknown _sounder_name_used (Should not happen, this is a bug!)')

                txcvr['channel_id']           = txcvr['channel_id'].strip(b'\x00')
                txcvr['spare1']               = txcvr['spare1'].strip(b'\x00')
                txcvr['spare2']               = txcvr['spare2'].strip(b'\x00')
                txcvr['spare3']               = txcvr['spare3'].strip(b'\x00')
                txcvr['spare4']               = txcvr['spare4'].strip(b'\x00')
                txcvr['gpt_software_version'] = txcvr['gpt_software_version'].strip(b'\x00')

                buf_indx += txcvr_header_size

        elif version == b'1':
            #CON1 only has a single data field:  beam_config, holding an xml string
            data['beam_config'] = raw_string[self.header_size(version):].strip(b'\x00')

        return data


if __name__ == "__main__":
    """
    wcsd_db_stage.py relies on the two print statements here as outputs for the ingest process.  
    DO NOT add or change the print statements under main
    """

    file = sys.argv[1]
    instrument = sys.argv[2]
    reader = SimradFileReader(instrument)
    reader.process_file(file)
    print(reader.metadata)
    # print(reader.errors)




