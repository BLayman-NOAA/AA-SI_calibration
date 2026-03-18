# -*- coding: utf-8 -*-

import os
import sys
import json
import hashlib
import datetime
from operator import itemgetter

from . import geometery_tools as gt


class BaseReader(object):
    def __init__(self):
        super(BaseReader, self).__init__()
        self.metadata = None
        self.file_path = None
        self.instrument = None
        self.recording_range = 0
        self.number_beams = 0
        self.swath = 0
        self.power = None
        self.pulse_length = None
        self.raw_nav = []
        self.lat = []
        self.lon = []
        self.frequencies = set()
        self.min_frequency = None
        self.max_frequency = None
        self.display_frequency = None
        self.start_time = None
        self.end_time = None
        self.errors = []
        self.type = None
        self.shape = None
        self.filename = None
        self.checksum = None
        self.file_geom = ()

    def reset(self):
        """Resets all file-level metadata attributes before next file

        """
        self.shape = None
        self.filename = None
        self.checksum = None
        self.file_geom = ()
        self.metadata = None
        self.file_path = None
        self.instrument = None
        self.recording_range = 0
        self.number_beams = 0
        self.swath = 0
        self.power = None
        self.pulse_length = None
        self.raw_nav = []
        self.lat = []
        self.lon = []
        self.frequencies = set()
        self.min_frequency = None
        self.max_frequency = None
        self.display_frequency = None
        self.start_time = None
        self.end_time = None
        self.errors = []

    @staticmethod
    def parse_exception(exception, location):
        """Method to convert exception information into string that can be
        passed back via the subprocess call.

        Args:
            exception: Exception that was thrown.
            location(str): Location in process where error occurred.

        Returns:
            message(str): String message created from exception.

        """
        message = (f'{type(exception).__name__}:{exception} occurred '
                   f'{location}')
        return message

    def process_file(self, file_path, check_only=False):
        """Main  method for processing file.

        Args:
            file_path(str): Full path to file to process.
            check_only(bool): Control whether file is processed or just
            check to make sure it's a valid file.

        """
        # Starting point for process method in instrument specific reader.
        self.filename = os.path.basename(file_path)
        fid = open(file_path, 'rb')

        # Initialize checksum hash.
        hashalg = getattr(hashlib, 'md5')()
        if True:
            hashalg.update('binary data blocks from reader')
        self.checksum = hashalg.hexdigest()
        fid.close()

    def process_frequencies(self):
        """Convert raw frequency information into what is needed for
        metadata use.

        """
        # process, sort, and add units to frequencies
        if self.frequencies:
            if self.type == 'Multibeam':
                self.min_frequency = round(min(self.frequencies))
                self.max_frequency = round(max(self.frequencies))
                if self.min_frequency == self.max_frequency:
                    self.display_frequency = f'{self.min_frequency} kHz'
                else:
                    self.display_frequency = (f'{self.min_frequency}-'
                                              f'{self.max_frequency} kHz')
                self.frequencies = None
            else:
                if self.type == 'Split' or self.type == 'Single' or self.type == 'Dual':
                    self.frequencies = [str(f)+'kHz' for f in self.frequencies]
                elif 'Split' in self.type and 'Wide Band' in self.type:
                    mixed_frequencies = set()
                    for f in self.frequencies:
                        if 'WkHz' not in f:
                            split_f = str(f) + 'kHz'
                            mixed_frequencies.add(split_f)
                        else:
                            mixed_frequencies.add(f)
                    self.frequencies = mixed_frequencies
                # convert set to sorted list. Sort by single numbers, then by ranges
                self.frequencies = sorted(list(self.frequencies), key=lambda x: int(
                    "".join([i for i in x if i.isdigit()])))
                self.display_frequency = ', '.join(f for f in self.frequencies)
        else:
            self.min_frequency = ''
            self.max_frequency = ''
            self.display_frequency = ''

    def get_metadata(self):
        """Get metadata.

        Return the metadata for this file as JSON format.

        Returns(json): JSON string containing metadata for this file.

        """
        if self.start_time:
            start = self.start_time.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            start = None

        if self.end_time:
            end = self.end_time.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            end = None

        metadata = {
            'FILE_NAME': self.filename,
            'INSTRUMENT': self.instrument,
            'START_TIME': start,
            'END_TIME': end,
            'SHAPE': self.get_shape(),
            'BOUNDS': self.get_bounds(),
            'COPIED_CHECKSUM': self.checksum,
            'FILE_PARAMETERS': self.get_parameters(),
            'FILE_GEOM': self.file_geom
        }

        self.metadata = json.dumps(metadata)

    def get_parameters(self):
        """Build dictionary of file parameters.

        Returns:
            params (dict): dictionary of file parameters.

        """
        # Leave keys camel case because these are the actual values used as
        # parameter names for now.
        if self.frequencies:
            frequency = list(self.frequencies)
        else:
            frequency = []
        params = {
                  'Beam_Type': self.type,
                  'Recording_Range': self.recording_range,
                  'Frequency': frequency,
                  'Display_Frequency': self.display_frequency,
                  'Power': self.power,
                  'Pulse_Length': self.pulse_length,
        }

        if self.type == 'Multibeam':
            params['Swath_Width'] = self.swath
            params['Number_of_Beams'] = self.number_beams
            params['Minimum_Frequency'] = self.min_frequency
            params['Maximum_Frequency'] = self.max_frequency

        if self.errors:
            params['Read_Errors'] = list(set(self.errors))

        return params

    def get_shape(self, time_interval_input=10):
        """Call geometry creation methods.

        Args:
            time_interval_input (int): Determines the time interval (in
            seconds) between GPS fixes to use when doing acceleration test.

        """
        # Test if there are enough navigation points.
        if not self.raw_nav:
            if self.instrument != "AZFP":
                self.errors.append('No navigation points')
            return ''
        elif len(self.raw_nav) == 1:
            # There is only one point. Add a slightly off second point so
            # geometry remains a line.
            self.errors.append('Only one point. Second point added')
            point = self.raw_nav[0]
            new_point = (point[0]+datetime.timedelta(seconds=3),
                         point[1]+0.0001, point[2]+0.0001)
            self.raw_nav.append(new_point)

        # Sort by timestamps held in the first tuple index (tuple format:
        # (time, lon, lat))
        self.raw_nav.sort(key=itemgetter(0))

        # Append to lat and lon list attributes.
        for entry in self.raw_nav:
            self.lon.append(round(entry[1], 5))
            self.lat.append(round(entry[2], 5))

        self.file_geom, wkt = gt.trackline(self.raw_nav,
                                           time_interval=time_interval_input)
        return wkt

    def get_bounds(self):
        """Get geographic bounding box for file.

        Returns(list): List containing geographic bounds [W, N. E. S].
        """
        # return if lats or lons are missing:
        if not self.lat or not self.lon:
            return []

        # Sort both lists so min is index 0 and max is index -1
        lats = sorted(self.lat)
        lons = sorted(self.lon)

        # Check values to figure out what hemispheres we are in and assign
        # bounds.
        if lons[0] < 0 < lons[-1]:
            # We are crossing 0 or 180, If it's 180 we need to split lons
            # into east and west lists and take min of each and take minimum
            # of both lists.
            if lons[0] < -170:
                easts = []
                wests = []
                for lon in lons:
                    if lon <= 0:
                        wests.append(lon)
                    else:
                        easts.append(lon)
                west = easts[0]
                east = wests[-1]

            else:
                west = lons[0]
                east = lons[-1]
        else:
            # We are all in the east or west hemisphere.
            west = lons[0]
            east = lons[-1]

        north = lats[-1]
        south = lats[0]

        return [round(west, 5), round(north, 5),
                round(east, 5), round(south, 5)]


if __name__ == "__main__":
    reader = BaseReader()
    reader.process_file(sys.argv[1])
    print(reader.get_metadata())



