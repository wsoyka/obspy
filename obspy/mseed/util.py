# -*- coding: utf-8 -*-
"""
Mini-SEED specific utilities.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from future.builtins import *  # NOQA
from future.utils import native_str

from obspy.mseed.headers import HPTMODULUS, clibmseed, FRAME, SAMPLESIZES, \
    ENDIAN, ENCODINGS, UNSUPPORTED_ENCODINGS, FIXED_HEADER_ACTIVITY_FLAGS, \
    FIXED_HEADER_DATA_QUAL_FLAGS, FIXED_HEADER_IO_CLOCK_FLAGS
from obspy import UTCDateTime
from obspy.core.util import scoreatpercentile
from struct import pack, unpack
import sys
import ctypes as C
import numpy as np
import math
import warnings
import os


def getStartAndEndTime(file_or_file_object):
    """
    Returns the start and end time of a Mini-SEED file or file-like object.

    :type file_or_file_object: str or file
    :param file_or_file_object: Mini-SEED file name or open file-like object
        containing a Mini-SEED record.
    :return: tuple (start time of first record, end time of last record)

    This method will return the start time of the first record and the end time
    of the last record. Keep in mind that it will not return the correct result
    if the records in the Mini-SEED file do not have a chronological ordering.

    The returned end time is the time of the last data sample and not the
    time that the last sample covers.

    .. rubric:: Example

    >>> from obspy.core.util import getExampleFile
    >>> filename = getExampleFile("BW.BGLD.__.EHE.D.2008.001.first_10_records")
    >>> getStartAndEndTime(filename)  # doctest: +NORMALIZE_WHITESPACE
        (UTCDateTime(2007, 12, 31, 23, 59, 59, 915000),
        UTCDateTime(2008, 1, 1, 0, 0, 20, 510000))

    It also works with an open file pointer. The file pointer itself will not
    be changed.

    >>> f = open(filename, 'rb')
    >>> getStartAndEndTime(f)  # doctest: +NORMALIZE_WHITESPACE
        (UTCDateTime(2007, 12, 31, 23, 59, 59, 915000),
        UTCDateTime(2008, 1, 1, 0, 0, 20, 510000))

    And also with a Mini-SEED file stored in a BytesIO

    >>> import io
    >>> file_object = io.BytesIO(f.read())
    >>> getStartAndEndTime(file_object)  # doctest: +NORMALIZE_WHITESPACE
        (UTCDateTime(2007, 12, 31, 23, 59, 59, 915000),
        UTCDateTime(2008, 1, 1, 0, 0, 20, 510000))
    >>> file_object.close()

    If the file pointer does not point to the first record, the start time will
    refer to the record it points to.

    >>> _ = f.seek(512)
    >>> getStartAndEndTime(f)  # doctest: +NORMALIZE_WHITESPACE
        (UTCDateTime(2008, 1, 1, 0, 0, 1, 975000),
        UTCDateTime(2008, 1, 1, 0, 0, 20, 510000))

    The same is valid for a file-like object.

    >>> file_object = io.BytesIO(f.read())
    >>> getStartAndEndTime(file_object)  # doctest: +NORMALIZE_WHITESPACE
        (UTCDateTime(2008, 1, 1, 0, 0, 1, 975000),
        UTCDateTime(2008, 1, 1, 0, 0, 20, 510000))
    >>> f.close()
    """
    # Get the starttime of the first record.
    info = getRecordInformation(file_or_file_object)
    starttime = info['starttime']
    # Get the end time of the last record.
    info = getRecordInformation(
        file_or_file_object,
        (info['number_of_records'] - 1) * info['record_length'])
    endtime = info['endtime']
    return starttime, endtime


def getTimingAndDataQuality(file_or_file_object):
    """
    Counts all data quality flags of the given Mini-SEED file and returns
    statistics about the timing quality if applicable.

    :type file_or_file_object: str or file
    :param file_or_file_object: Mini-SEED file name or open file-like object
        containing a Mini-SEED record.

    :return: Dictionary with information about the timing quality and the data
        quality flags.

    .. rubric:: Data quality

    This method will count all set data quality flag bits in the fixed section
    of the data header in a Mini-SEED file and returns the total count for each
    flag type.

    ========  =================================================
    Bit       Description
    ========  =================================================
    [Bit 0]   Amplifier saturation detected (station dependent)
    [Bit 1]   Digitizer clipping detected
    [Bit 2]   Spikes detected
    [Bit 3]   Glitches detected
    [Bit 4]   Missing/padded data present
    [Bit 5]   Telemetry synchronization error
    [Bit 6]   A digital filter may be charging
    [Bit 7]   Time tag is questionable
    ========  =================================================

    .. rubric:: Timing quality

    If the file has a Blockette 1001 statistics about the timing quality will
    also be returned. See the doctests for more information.

    This method will read the timing quality in Blockette 1001 for each
    record in the file if available and return the following statistics:
    Minima, maxima, average, median and upper and lower quantile.
    Quantiles are calculated using a integer round outwards policy: lower
    quantiles are rounded down (probability < 0.5), and upper quantiles
    (probability > 0.5) are rounded up.
    This gives no more than the requested probability in the tails, and at
    least the requested probability in the central area.
    The median is calculating by either taking the middle value or, with an
    even numbers of values, the average between the two middle values.

    .. rubric:: Example

    >>> from obspy.core.util import getExampleFile
    >>> filename = getExampleFile("qualityflags.mseed")
    >>> tq = getTimingAndDataQuality(filename)
    >>> for k, v in tq.items():
    ...     print(k, v)
    data_quality_flags [9, 8, 7, 6, 5, 4, 3, 2]

    Also works with file pointers and BytesIOs.

    >>> f = open(filename, 'rb')
    >>> tq = getTimingAndDataQuality(f)
    >>> for k, v in tq.items():
    ...     print(k, v)
    data_quality_flags [9, 8, 7, 6, 5, 4, 3, 2]

    >>> import io
    >>> file_object = io.BytesIO(f.read())
    >>> f.close()
    >>> tq = getTimingAndDataQuality(file_object)
    >>> for k, v in tq.items():
    ...     print(k, v)
    data_quality_flags [9, 8, 7, 6, 5, 4, 3, 2]

    If the file pointer or BytesIO position does not correspond to the first
    record the omitted records will be skipped.

    >>> _ = file_object.seek(1024, 1)
    >>> tq = getTimingAndDataQuality(file_object)
    >>> for k, v in tq.items():
    ...     print(k, v)
    data_quality_flags [8, 8, 7, 6, 5, 4, 3, 2]
    >>> file_object.close()

    Reading a file with Blockette 1001 will return timing quality statistics.
    The data quality flags will always exists because they are part of the
    fixed Mini-SEED header and therefore need to be in every Mini-SEED file.

    >>> filename = getExampleFile("timingquality.mseed")
    >>> tq = getTimingAndDataQuality(filename)
    >>> for k, v in sorted(tq.items()):
    ...     print(k, v)
    data_quality_flags [0, 0, 0, 0, 0, 0, 0, 0]
    timing_quality_average 50.0
    timing_quality_lower_quantile 25.0
    timing_quality_max 100.0
    timing_quality_median 50.0
    timing_quality_min 0.0
    timing_quality_upper_quantile 75.0

    Also works with file pointers and BytesIOs.

    >>> f = open(filename, 'rb')
    >>> tq = getTimingAndDataQuality(f)
    >>> for k, v in sorted(tq.items()):
    ...     print(k, v)
    data_quality_flags [0, 0, 0, 0, 0, 0, 0, 0]
    timing_quality_average 50.0
    timing_quality_lower_quantile 25.0
    timing_quality_max 100.0
    timing_quality_median 50.0
    timing_quality_min 0.0
    timing_quality_upper_quantile 75.0

    >>> file_object = io.BytesIO(f.read())
    >>> f.close()
    >>> tq = getTimingAndDataQuality(file_object)
    >>> for k, v in sorted(tq.items()):
    ...     print(k, v)
    data_quality_flags [0, 0, 0, 0, 0, 0, 0, 0]
    timing_quality_average 50.0
    timing_quality_lower_quantile 25.0
    timing_quality_max 100.0
    timing_quality_median 50.0
    timing_quality_min 0.0
    timing_quality_upper_quantile 75.0
    >>> file_object.close()
    """
    # Read the first record to get a starting point and.
    info = getRecordInformation(file_or_file_object)
    # Keep track of the extracted information.
    quality_count = [0, 0, 0, 0, 0, 0, 0, 0]
    timing_quality = []
    offset = 0

    # Loop over each record. A valid record needs to have a record length of at
    # least 256 bytes.
    while offset <= (info['filesize'] - 256):
        this_info = getRecordInformation(file_or_file_object, offset)
        # Add the timing quality.
        if 'timing_quality' in this_info:
            timing_quality.append(float(this_info['timing_quality']))
        # Add the value of each bit to the quality_count.
        for _i in range(8):
            if (this_info['data_quality_flags'] & (1 << _i)) != 0:
                quality_count[_i] += 1
        offset += this_info['record_length']

    # Collect the results in a dictionary.
    result = {'data_quality_flags': quality_count}

    # Parse of the timing quality list.
    count = len(timing_quality)
    timing_quality = sorted(timing_quality)
    # If no timing_quality was collected just return an empty dictionary.
    if count == 0:
        return result
    # Otherwise calculate some statistical values from the timing quality.
    result['timing_quality_min'] = min(timing_quality)
    result['timing_quality_max'] = max(timing_quality)
    result['timing_quality_average'] = sum(timing_quality) / count
    result['timing_quality_median'] = \
        scoreatpercentile(timing_quality, 50, issorted=False)
    result['timing_quality_lower_quantile'] = \
        scoreatpercentile(timing_quality, 25, issorted=False)
    result['timing_quality_upper_quantile'] = \
        scoreatpercentile(timing_quality, 75, issorted=False)
    return result


def getRecordInformation(file_or_file_object, offset=0, endian=None):
    """
    Returns record information about given files and file-like object.

    :param endian: If given, the byte order will be enforced. Can be either "<"
        or ">". If None, it will be determined automatically.
        Defaults to None.

    .. rubric:: Example

    >>> from obspy.core.util import getExampleFile
    >>> filename = getExampleFile("test.mseed")
    >>> ri = getRecordInformation(filename)
    >>> for k, v in sorted(ri.items()):
    ...     print(k, v)
    activity_flags 0
    byteorder >
    data_quality_flags 0
    encoding 11
    endtime 2003-05-29T02:15:51.518400Z
    excess_bytes 0
    filesize 8192
    io_and_clock_flags 0
    npts 5980
    number_of_records 2
    record_length 4096
    samp_rate 40.0
    starttime 2003-05-29T02:13:22.043400Z
    """
    if isinstance(file_or_file_object, (str, native_str)):
        with open(file_or_file_object, 'rb') as f:
            info = _getRecordInformation(f, offset=offset, endian=endian)
    else:
        info = _getRecordInformation(file_or_file_object, offset=offset,
                                     endian=endian)
    return info


def _getRecordInformation(file_object, offset=0, endian=None):
    """
    Searches the first Mini-SEED record stored in file_object at the current
    position and returns some information about it.

    If offset is given, the Mini-SEED record is assumed to start at current
    position + offset in file_object.

    :param endian: If given, the byte order will be enforced. Can be either "<"
        or ">". If None, it will be determined automatically.
        Defaults to None.
    """
    initial_position = file_object.tell()
    record_start = initial_position
    samp_rate = None

    info = {}

    # Apply the offset.
    file_object.seek(offset, 1)
    record_start += offset

    # Get the size of the buffer.
    file_object.seek(0, 2)
    info['filesize'] = int(file_object.tell() - record_start)
    file_object.seek(record_start, 0)

    # check current position
    if info['filesize'] % 256 != 0:
        # if a multiple of minimal record length 256
        record_start = 0
    elif file_object.read(8)[6:7] not in [b'D', b'R', b'Q', b'M']:
        # if valid data record start at all starting with D, R, Q or M
        record_start = 0
    file_object.seek(record_start, 0)

    # check if full SEED or Mini-SEED
    if file_object.read(8)[6:7] == b'V':
        # found a full SEED record - seek first Mini-SEED record
        # search blockette 005, 008 or 010 which contain the record length
        blockette_id = file_object.read(3)
        while blockette_id not in [b'010', b'008', b'005']:
            if not blockette_id.startswith(b'0'):
                msg = "SEED Volume Index Control Headers: blockette 0xx" + \
                      " expected, got %s"
                raise Exception(msg % blockette_id)
            # get length and jump to end of current blockette
            blockette_len = int(file_object.read(4))
            file_object.seek(blockette_len - 7, 1)
            # read next blockette id
            blockette_id = file_object.read(3)
        # Skip the next bytes containing length of the blockette and version
        file_object.seek(8, 1)
        # get record length
        rec_len = pow(2, int(file_object.read(2)))
        # reset file pointer
        file_object.seek(record_start, 0)
        # cycle through file using record length until first data record found
        while file_object.read(7)[6:7] not in [b'D', b'R', b'Q', b'M']:
            record_start += rec_len
            file_object.seek(record_start, 0)

    # Use the date to figure out the byte order.
    file_object.seek(record_start + 20, 0)
    # Capital letters indicate unsigned quantities.
    data = file_object.read(28)
    fmt = lambda s: native_str('%sHHBBBxHHhhBBBxlxxH' % s)
    if endian is None:
        try:
            endian = ">"
            values = unpack(fmt(endian), data)
            starttime = UTCDateTime(
                year=values[0], julday=values[1],
                hour=values[2], minute=values[3], second=values[4],
                microsecond=values[5] * 100)
        except:
            endian = "<"
            values = unpack(fmt(endian), data)
            starttime = UTCDateTime(
                year=values[0], julday=values[1],
                hour=values[2], minute=values[3], second=values[4],
                microsecond=values[5] * 100)
    else:
        values = unpack(fmt(endian), data)
        try:
            starttime = UTCDateTime(
                year=values[0], julday=values[1],
                hour=values[2], minute=values[3], second=values[4],
                microsecond=values[5] * 100)
        except:
            msg = ("Invalid starttime found. The passed byte order is likely "
                   "wrong.")
            raise ValueError(msg)
    npts = values[6]
    info['npts'] = npts
    samp_rate_factor = values[7]
    samp_rate_mult = values[8]
    info['activity_flags'] = values[9]
    # Bit 1 of the activity flags.
    time_correction_applied = bool(info['activity_flags'] & 2)
    info['io_and_clock_flags'] = values[10]
    info['data_quality_flags'] = values[11]
    time_correction = values[12]
    blkt_offset = values[13]

    # Correct the starttime if applicable.
    if (time_correction_applied is False) and time_correction:
        # Time correction is in units of 0.0001 seconds.
        starttime += time_correction * 0.0001

    # Traverse the blockettes and parse Blockettes 100, 500, 1000 and/or 1001
    # if any of those is found.
    while blkt_offset:
        file_object.seek(record_start + blkt_offset, 0)
        blkt_type, next_blkt = unpack(native_str('%sHH' % endian),
                                      file_object.read(4))
        if next_blkt != 0 and (next_blkt < 4 or next_blkt - 4 <= blkt_offset):
            msg = ('Invalid blockette offset (%d) less than or equal to '
                   'current offset (%d)') % (next_blkt, blkt_offset)
            raise ValueError(msg)
        blkt_offset = next_blkt

        # Parse in order of likeliness.
        if blkt_type == 1000:
            encoding, word_order, record_length = \
                unpack(native_str('%sBBB' % endian),
                       file_object.read(3))
            if ENDIAN[word_order] != endian:
                msg = 'Inconsistent word order.'
                warnings.warn(msg, UserWarning)
            info['encoding'] = encoding
            info['record_length'] = 2 ** record_length
        elif blkt_type == 1001:
            info['timing_quality'], mu_sec = \
                unpack(native_str('%sBb' % endian),
                       file_object.read(2))
            starttime += float(mu_sec) / 1E6
        elif blkt_type == 500:
            file_object.seek(14, 1)
            mu_sec = unpack(native_str('%sb' % endian),
                            file_object.read(1))[0]
            starttime += float(mu_sec) / 1E6
        elif blkt_type == 100:
            samp_rate = unpack(native_str('%sf' % endian),
                               file_object.read(4))[0]

    # If samprate not set via blockette 100 calculate the sample rate according
    # to the SEED manual.
    if not samp_rate:
        if (samp_rate_factor > 0) and (samp_rate_mult) > 0:
            samp_rate = float(samp_rate_factor * samp_rate_mult)
        elif (samp_rate_factor > 0) and (samp_rate_mult) < 0:
            samp_rate = -1.0 * float(samp_rate_factor) / float(samp_rate_mult)
        elif (samp_rate_factor < 0) and (samp_rate_mult) > 0:
            samp_rate = -1.0 * float(samp_rate_mult) / float(samp_rate_factor)
        elif (samp_rate_factor < 0) and (samp_rate_mult) < 0:
            samp_rate = -1.0 / float(samp_rate_factor * samp_rate_mult)
        else:
            # if everything is unset or 0 set sample rate to 1
            samp_rate = 1

    info['samp_rate'] = samp_rate

    info['starttime'] = starttime
    # Endtime is the time of the last sample.
    info['endtime'] = starttime + (npts - 1) / samp_rate
    info['byteorder'] = endian

    info['number_of_records'] = int(info['filesize'] //
                                    info['record_length'])
    info['excess_bytes'] = int(info['filesize'] % info['record_length'])

    # Reset file pointer.
    file_object.seek(initial_position, 0)
    return info


def _ctypesArray2NumpyArray(buffer_, buffer_elements, sampletype):
    """
    Takes a Ctypes array and its length and type and returns it as a
    NumPy array.

    This works by reference and no data is copied.

    :param buffer_: Ctypes c_void_p pointer to buffer.
    :param buffer_elements: length of the whole buffer
    :param sampletype: type of sample, on of "a", "i", "f", "d"
    """
    # Allocate NumPy array to move memory to
    numpy_array = np.empty(buffer_elements, dtype=sampletype)
    datptr = numpy_array.ctypes.get_data()
    # Manually copy the contents of the C allocated memory area to
    # the address of the previously created NumPy array
    C.memmove(datptr, buffer_, buffer_elements * SAMPLESIZES[sampletype])
    return numpy_array


def _convertMSRToDict(m):
    """
    Internal method used for setting header attributes.
    """
    h = {}
    attributes = ('network', 'station', 'location', 'channel',
                  'dataquality', 'starttime', 'samprate',
                  'samplecnt', 'numsamples', 'sampletype')
    # loop over attributes
    for _i in attributes:
        h[_i] = getattr(m, _i)
    return h


def _convertDatetimeToMSTime(dt):
    """
    Takes a obspy.util.UTCDateTime object and returns an epoch time in ms.

    :param dt: obspy.util.UTCDateTime object.
    """
    _fsec, _sec = math.modf(dt.timestamp)
    return int(round(_fsec * HPTMODULUS)) + int(_sec * HPTMODULUS)


def _convertMSTimeToDatetime(timestring):
    """
    Takes a Mini-SEED timestamp and returns a obspy.util.UTCDateTime object.

    :param timestamp: Mini-SEED timestring (Epoch time string in ms).
    """
    return UTCDateTime(timestring / HPTMODULUS)


def _unpackSteim1(data_string, npts, swapflag=0, verbose=0):
    """
    Unpack steim1 compressed data given as string.

    :param data_string: data as string
    :param npts: number of data points
    :param swapflag: Swap bytes, defaults to 0
    :return: Return data as numpy.ndarray of dtype int32
    """
    dbuf = data_string
    datasize = len(dbuf)
    samplecnt = npts
    datasamples = np.empty(npts, dtype=np.int32)
    diffbuff = np.empty(npts, dtype=np.int32)
    x0 = C.c_int32()
    xn = C.c_int32()
    nsamples = clibmseed.msr_unpack_steim1(
        C.cast(dbuf, C.POINTER(FRAME)), datasize,
        samplecnt, samplecnt, datasamples, diffbuff,
        C.byref(x0), C.byref(xn), swapflag, verbose)
    if nsamples != npts:
        raise Exception("Error in unpack_steim1")
    return datasamples


def _unpackSteim2(data_string, npts, swapflag=0, verbose=0):
    """
    Unpack steim2 compressed data given as string.

    :param data_string: data as string
    :param npts: number of data points
    :param swapflag: Swap bytes, defaults to 0
    :return: Return data as numpy.ndarray of dtype int32
    """
    dbuf = data_string
    datasize = len(dbuf)
    samplecnt = npts
    datasamples = np.empty(npts, dtype=np.int32)
    diffbuff = np.empty(npts, dtype=np.int32)
    x0 = C.c_int32()
    xn = C.c_int32()
    nsamples = clibmseed.msr_unpack_steim2(
        C.cast(dbuf, C.POINTER(FRAME)), datasize,
        samplecnt, samplecnt, datasamples, diffbuff,
        C.byref(x0), C.byref(xn), swapflag, verbose)
    if nsamples != npts:
        raise Exception("Error in unpack_steim2")
    return datasamples


def set_flags_in_fixed_headers(filename, flags):
    """
    Updates a given MiniSEED file with some fixed header flags.

    :type filename: string
    :param filename: name of the MiniSEED file to be changed
    :type flags: dict
    :param flags: the flags to update in the MiniSEED file

    Flags are stored as a nested dictionary:

    .. code-block:: python

        { trace_id: { flag_group : { flag_name : flag_value, ... }, ...}, ...}

    with:

    * ``trace_id``: a string identifying the trace. A string looking like
      ``NETWORK.STATION.LOCATION.CHANNEL`` is expected, the values will be
      compared to those found in the fixed header of every record. An empty
      field will be interpreted  as "every possible value", so ``"..."`` will
      apply to every single trace in the file. Padding spaces are ignored.
    * ``flag_group``: which flag group is to be changed. One of
      ``'activity_flags'``, ``'io_clock_flags'``, ``'data_qual_flags'`` is
      expected. Invalid flag groups will be ignored.
    * ``flag_name``: the name of the flag. Possible values are matched with
      ``obspy.mseed.headers.FIXED_HEADER_ACTIVITY_FLAGS``,
      ``FIXED_HEADER_IO_CLOCK_FLAGS`` or ``FIXED_HEADER_DATA_QUAL_FLAGS``
      depending on the flag_group. Invalid flags are ignored.
    * ``flag_value``: the value you want for this flag. The method will try to
      convert your value to a boolean, this should not break but might set
      unexpected values in your records.

    Example: to add a *Calibration Signals Presents* flag (which belongs to the
    Activity Flags section of the fixed header) to every record, flags should
    be:

    .. code-block:: python

        { "..." : { "activity_flags" : { "calib_signal" : True }}}

    Raises an IOError if the file is not a MiniSEED file.
    """

    # import has to be here to break import loop
    from obspy.mseed.core import isMSEED
    # Basic check
    if not os.path.isfile(filename) or not isMSEED(filename):
        raise IOError("File %s is not a valid MiniSEED file" % filename)
    filesize = os.path.getsize(filename)

    # Nested dictionaries to allow empty strings as wildcards
    class NestedDict(dict):
        def __missing__(self, key):
            value = self[key] = type(self)()
            return value
    # Define wildcard character
    wildcard = ""

    # Check channel identifier value
    flags_bytes = NestedDict()
    for (key, value) in flags.items():
        split_key = key.split(".")
        if len(split_key) != 4:
            msg = "Invalid channel identifier. " +\
                  "Expected 'Network.Station.Location.Channel' " +\
                  "(empty fields allowed), got '%s'."
            raise ValueError(msg % key)

        # Convert flags to bytes : activity
        if 'activity_flags' in value:
            act_flag = _convertFlagsToRawByte(FIXED_HEADER_ACTIVITY_FLAGS,
                                              value['activity_flags'])
        else:
            act_flag = 0
        # Convert flags to bytes : i/o and clock
        if 'io_clock_flags' in value:
            io_clock_flag = _convertFlagsToRawByte(FIXED_HEADER_IO_CLOCK_FLAGS,
                                                   value['io_clock_flags'])
        else:
            io_clock_flag = 0

        # Convert flags to bytes : data quality flags
        if 'data_qual_flags' in value:
            data_qual_flag = _convertFlagsToRawByte(
                FIXED_HEADER_DATA_QUAL_FLAGS,
                value['data_qual_flags'])
        else:
            data_qual_flag = 0

        flagsbytes = pack("BBB", act_flag, io_clock_flag, data_qual_flag)

        # Remove padding spaces and store in new dict
        net = split_key[0].strip()
        sta = split_key[1].strip()
        loc = split_key[2].strip()
        chan = split_key[3].strip()
        flags_bytes[net][sta][loc][chan] = flagsbytes

    # Open file
    with open(filename, 'r+b') as mseed_file:
        # Run through all records
        while mseed_file.tell() < filesize:
            record_start = mseed_file.tell()

            # Ignore sequence number and data header
            mseed_file.seek(8, os.SEEK_CUR)
            # Read identifier
            sta = mseed_file.read(5).strip()
            loc = mseed_file.read(2).strip()
            chan = mseed_file.read(3).strip()
            net = mseed_file.read(2).strip()

            # Search the nested dict for the network identifier
            if net in flags_bytes:
                dict_to_use = flags_bytes[net]
            elif wildcard in flags_bytes:
                dict_to_use = flags_bytes[wildcard]
            else:
                dict_to_use = None

            # Search the nested dict for the station identifier
            if dict_to_use is not None and sta in dict_to_use:
                dict_to_use = dict_to_use[sta]
            elif dict_to_use is not None and wildcard in dict_to_use:
                dict_to_use = dict_to_use[wildcard]
            else:
                dict_to_use = None

            # Search the nested dict for the location identifier
            if dict_to_use is not None and loc in dict_to_use:
                dict_to_use = dict_to_use[loc]
            elif dict_to_use is not None and wildcard in dict_to_use:
                dict_to_use = dict_to_use[wildcard]
            else:
                dict_to_use = None

            # Search the nested dict for the channel identifier
            if dict_to_use is not None and chan in dict_to_use:
                flags_value = dict_to_use[chan]
            elif dict_to_use is not None and wildcard in dict_to_use:
                flags_value = dict_to_use[wildcard]
            else:
                flags_value = None

            if flags_value is not None:
                mseed_file.seek(16, os.SEEK_CUR)
                # Update flags*
                mseed_file.write(flags_value)
                # Seek to "First blockette"
                mseed_file.seek(7, os.SEEK_CUR)
            else:
                # Seek directly to "First blockette"
                mseed_file.seek(26, os.SEEK_CUR)

            # Read record length in blockette 1000 to seek to the next record
            next_blockette = unpack(native_str(">H"), mseed_file.read(2))[0]
            reclen = -1
            while next_blockette != 0:
                mseed_file.seek(record_start + next_blockette, os.SEEK_SET)
                blkt_nbr = unpack(native_str(">H"), mseed_file.read(2))[0]
                if blkt_nbr == 1000:
                    mseed_file.seek(4, os.SEEK_CUR)
                    reclen_pow = unpack(native_str("B"), mseed_file.read(1))[0]
                    reclen = 2**reclen_pow
                    break
                else:
                    next_blockette = unpack(native_str(">H"),
                                            mseed_file.read(2))[0]

            if reclen == -1:
                msg = "Invalid MiniSEED file. No blockette 1000 was found."
                raise IOError(msg)
            else:
                mseed_file.seek(record_start + reclen, os.SEEK_SET)


def _convertFlagsToRawByte(expected_flags, user_flags):
    """
    Converts a flag dictionary to a byte, ready to be encoded in a MiniSEED
    header.

    This is a utility function for set_flags_in_fixed_headers and is not
    designed to be called by someone else.

    expected_signals describes all the possible bit names for the user flags
    and their place in the result byte. Expected: dict { exponent: bit_name }.
    The fixed header flags are available in obspy.mseed.headers as
    FIXED_HEADER_ACTIVITY_FLAGS, FIXED_HEADER_DATA_QUAL_FLAGS and
    FIXED_HEADER_IO_CLOCK_FLAGS.

    This expects a user_flags as a dictionary { bit_name : value }. bit_name is
    compared to the expected_signals, and its value is converted to bool.
    Missing values are considered false.

    :type expected_flags: dict {int: str}
    :param expected_flags: every possible flag in this field, with its offset
    :type user_flags: dict {str: bool}
    :param user_flags: user defined flags and its value
    :return:

    """

    flag_byte = 0

    for (bit, key) in expected_flags.items():
        if key in user_flags and bool(user_flags[key]):
            flag_byte += 2**bit

    return flag_byte


def shiftTimeOfFile(input_file, output_file, timeshift):
    """
    Takes a MiniSEED file and shifts the time of every record by the given
    amount.

    The same could be achieved by reading the MiniSEED file with ObsPy,
    modifying the starttime and writing it again. The problem with this
    approach is that some record specific flags and special blockettes might
    not be conserved. This function directly operates on the file and simply
    changes some header fields, not touching the rest, thus preserving it.

    Will only work correctly if all records have the same record length which
    usually should be the case.

    All times are in 0.0001 seconds, that is in 1/10000 seconds. NOT ms but one
    order of magnitude smaller! This is due to the way time corrections are
    stored in the MiniSEED format.

    :type input_file: str
    :param input_file: The input filename.
    :type output_file: str
    :param output_file: The output filename.
    :type timeshift: int
    :param timeshift: The time-shift to be applied in 0.0001, e.g. 1E-4
        seconds. Use an integer number.

    Please do NOT use identical input and output files because if something
    goes wrong, your data WILL be corrupted/destroyed. Also always check the
    resulting output file.

    .. rubric:: Technical details

    The function will loop over every record and change the "Time correction"
    field in the fixed section of the MiniSEED data header by the specified
    amount. Unfortunately a further flag (bit 1 in the "Activity flags" field)
    determines whether or not the time correction has already been applied to
    the record start time. If it has not, all is fine and changing the "Time
    correction" field is enough. Otherwise the actual time also needs to be
    changed.

    One further detail: If bit 1 in the "Activity flags" field is 1 (True) and
    the "Time correction" field is 0, then the bit will be set to 0 and only
    the time correction will be changed thus avoiding the need to change the
    record start time which is preferable.
    """
    timeshift = int(timeshift)
    # A timeshift of zero makes no sense.
    if timeshift == 0:
        msg = "The timeshift must to be not equal to 0."
        raise ValueError(msg)

    # Get the necessary information from the file.
    info = getRecordInformation(input_file)
    record_length = info["record_length"]

    byteorder = info["byteorder"]
    sys_byteorder = "<" if (sys.byteorder == "little") else ">"
    doSwap = False if (byteorder == sys_byteorder) else True

    # This is in this scenario somewhat easier to use than BytesIO because one
    # can directly modify the data array.
    data = np.fromfile(input_file, dtype=np.uint8)
    array_length = len(data)
    record_offset = 0
    # Loop over every record.
    while True:
        remaining_bytes = array_length - record_offset
        if remaining_bytes < 48:
            if remaining_bytes > 0:
                msg = "%i excessive byte(s) in the file. " % remaining_bytes
                msg += "They will be appended to the output file."
                warnings.warn(msg)
            break
        # Use a slice for the current record.
        current_record = data[record_offset: record_offset + record_length]
        record_offset += record_length

        activity_flags = current_record[36]
        is_time_correction_applied = bool(activity_flags & 2)

        current_time_shift = current_record[40:44]
        current_time_shift.dtype = np.int32
        if doSwap:
            current_time_shift = current_time_shift.byteswap(False)
        current_time_shift = current_time_shift[0]

        # If the time correction has been applied, but there is no actual
        # time correction, then simply set the time correction applied
        # field to false and process normally.
        # This should rarely be the case.
        if current_time_shift == 0 and is_time_correction_applied:
            # This sets bit 2 of the activity flags to 0.
            current_record[36] = current_record[36] & (~2)
            is_time_correction_applied = False
        # This is the case if the time correction has been applied. This
        # requires some more work by changing both, the actual time and the
        # time correction field.
        elif is_time_correction_applied:
            msg = "The timeshift can only be applied by actually changing the "
            msg += "time. This is experimental. Please make sure the output "
            msg += "file is correct."
            warnings.warn(msg)
            # The whole process is not particularly fast or optimized but
            # instead intends to avoid errors.
            # Get the time variables.
            time = current_record[20:30]
            year = time[0:2]
            julday = time[2:4]
            hour = time[4:5]
            minute = time[5:6]
            second = time[6:7]
            msecs = time[8:10]
            # Change dtype of multibyte values.
            year.dtype = np.uint16
            julday.dtype = np.uint16
            msecs.dtype = np.uint16
            if doSwap:
                year = year.byteswap(False)
                julday = julday.byteswap(False)
                msecs = msecs.byteswap(False)
            dtime = UTCDateTime(year=year[0], julday=julday[0], hour=hour[0],
                                minute=minute[0], second=second[0],
                                microsecond=msecs[0] * 100)
            dtime += (float(timeshift) / 10000)
            year[0] = dtime.year
            julday[0] = dtime.julday
            hour[0] = dtime.hour
            minute[0] = dtime.minute
            second[0] = dtime.second
            msecs[0] = dtime.microsecond / 100
            # Swap again.
            if doSwap:
                year = year.byteswap(False)
                julday = julday.byteswap(False)
                msecs = msecs.byteswap(False)
            # Change dtypes back.
            year.dtype = np.uint8
            julday.dtype = np.uint8
            msecs.dtype = np.uint8
            # Write to current record.
            time[0:2] = year[:]
            time[2:4] = julday[:]
            time[4] = hour[:]
            time[5] = minute[:]
            time[6] = second[:]
            time[8:10] = msecs[:]
            current_record[20:30] = time[:]

        # Now modify the time correction flag.
        current_time_shift += timeshift
        current_time_shift = np.array([current_time_shift], np.int32)
        if doSwap:
            current_time_shift = current_time_shift.byteswap(False)
        current_time_shift.dtype = np.uint8
        current_record[40:44] = current_time_shift[:]

    # Write to the output file.
    data.tofile(output_file)


def _convert_and_check_encoding_for_writing(encoding):
    """
    Helper function to handle and test encodings.

    If encoding is a string, it will be converted to the appropriate
    integer. It will furthermore be checked if the specified encoding can be
    written using libmseed. Appropriate errors will be raised if necessary.
    """
    # Check if encoding kwarg is set and catch invalid encodings.
    encoding_strings = dict([(v[0], k) for (k, v) in ENCODINGS.items()])

    try:
        encoding = int(encoding)
    except:
        pass

    if isinstance(encoding, int):
        if (encoding in ENCODINGS and ENCODINGS[encoding][3] is False) or \
                encoding in UNSUPPORTED_ENCODINGS:
            msg = ("Encoding %i cannot be written with ObsPy. Please "
                   "use another encoding.") % encoding
            raise ValueError(msg)
        elif encoding not in ENCODINGS:
            raise ValueError("Unknown encoding: %i." % encoding)
    else:
        if encoding not in encoding_strings:
            raise ValueError("Unknown encoding: '%s'." % str(encoding))
        elif ENCODINGS[encoding_strings[encoding]][3] is False:
            msg = ("Encoding '%s' cannot be written with ObsPy. Please "
                   "use another encoding.") % encoding
            raise ValueError(msg)
        encoding = encoding_strings[encoding]
    return encoding


if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
