# -*- coding: utf-8 -*-
'''
Common custom error used in the WCSD Packager file readers

Created by Chuck Anderson <charles.anderson@noaa.gov>
NOAA National Centers for Environmental Information


Revised 6/2016
'''
class ReaderErrors(Exception):
    """Base class for custom reader exceptions"""
    pass

class NoAllFile(ReaderErrors):
    """
    Error when there are no position datagrams in .wcd files and
    packager can not find a corresponding .all file when packaging\
    files from kongsberg EMxxx instruments
    """
    def __init__(self, message='No corresponding .all file found'):
        self.message = message

    def __str__(self):
        return self.message

class FileTypeError(ReaderErrors):
    """
    Error raised when the file is not from the specified instrument
    """
    def __init__(self, filename,  instrument):
        self.message = 'File "{}" is not an {} file or is bad from the first bytes'.format(filename,  instrument)

    def __str__(self):
        return self.message

class readerEOF(ReaderErrors):
    """
    Error raised when end of file hit (triggered by failure to read
    datagram header)
    """
    def __init__(self):
        self.message = 'End of file reached'

    def __str__(self):
        return self.message


class FileVersionError(ReaderErrors):
    """
    Error raised when .dt4 file version is older than version 2.0
    (indicated when reading the file header)
    """
    def __init__(self, filename):
        self.message = (f'File {filename} uses an outdated file format version.'
                        f'Contact BioSonics directly for assistance, as per the '
                        f'BioSonics File Format manual')

    def __str__(self):
        return self.message

class TupleError(ReaderErrors):
    """
    Error raised when processing a specific tuple type in a
    BioSonics .dt4 file
    """
    def __init__(self, filename, tuple_type):
        self.message = (f'An error occured while processing the {tuple_type}'
                        f' tuple in the {filename} File')

    def __str__(self):
        return self.message