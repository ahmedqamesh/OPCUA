#!/usr/bin/python
# -*- coding: utf-8 -*-

# Standard library modules
import os
import random as rdm
import logging
from logging.handlers import RotatingFileHandler
from math import ceil
from time import strftime, sleep
from datetime import timedelta
from argparse import ArgumentParser

# Third party modules
import coloredlogs as cl
import verboselogs
from canlib import canlib, Frame

# Other files
try:
    from . import CANopenConstants as coc
    from .CANopenConstants import sdoAbortCodes as SAC
    from .objectDictionary import objectDictionary as od
    from .extend_logging import extend_logging, removeAllHandlers
except (ModuleNotFoundError, ImportError):
    import CANopenConstants as coc
    from CANopenConstants import sdoAbortCodes as SAC
    from objectDictionary import objectDictionary as od
    from extend_logging import extend_logging, removeAllHandlers


PSPP_MAX_VALUES = [256, 256, 4, 256, 4, 4, 256, 8, 256, 4, 8, 256, 256]


class ChipNotConnectedError(Exception):
    pass


class CANopenDCSController(object):

    def __init__(self, channel=None, bitrate=canlib.canBITRATE_125K,
                 nodeId=None, loglevel=None,
                 logformat='%(asctime)s %(levelname)-8s %(message)s'):

        if channel is None:
            channel = 0
        if nodeId is None:
            nodeId = 42
        if loglevel is None:
            loglevel = logging.NOTICE

        self.__state = 0

        # Initialize logging
        extend_logging()
        verboselogs.install()
        self.logger = logging.getLogger(os.path.basename(__name__))
        self.logger.setLevel(logging.DEBUG)
        scrdir = os.path.dirname(os.path.abspath(__file__))
        self.canLogger = logging.getLogger('CAN_messages')
        self.canLogger.setLevel(logging.DEBUG)
        fname = os.path.join(scrdir, 'log', strftime('%Y-%m-%d_%H-%M-%S_'))
        self.__fh = RotatingFileHandler(fname + 'DCSController.log',
                                        backupCount=10,
                                        maxBytes=10 * 1024 * 1024)
        self.__cfh = RotatingFileHandler(fname + 'CANmsg.log', backupCount=10,
                                         maxBytes=10 * 1024 * 1024)
        fmt = logging.Formatter(logformat)
        self.__fh.setFormatter(fmt)
        self.__cfh.setFormatter(fmt)
        cl.install(fmt=logformat, level=loglevel, isatty=True)
        self.__fh.setLevel(logging.DEBUG)
        self.__cfh.setLevel(logging.DEBUG)
        self.logger.addHandler(self.__fh)
        self.canLogger.addHandler(self.__cfh)
        self.canLogger.info(coc.MSGHEADER)

        # Intialize object dictionary
        fp = os.path.join(scrdir, 'CANControllerForPSPPv1.eds')
        self.__od = od.from_eds(self.logger, fp, 42, True)

        # Initialize library and open channel
        self.__channel = channel
        self.__bitrate = bitrate
        self.__nodeId = nodeId
        self.__toggleBit = False
        self.__ch = canlib.openChannel(channel, canlib.canOPEN_ACCEPT_VIRTUAL)
        self.logger.success(str(self))
        self.__state = 127
        self.__ch.setBusParams(bitrate)
        self.__ch.busOn()
        self.logger.success('You are in \'Bus On\' state!')

    def __str__(self):
        chdataname = canlib.ChannelData(self.__channel).device_name
        chdata_EAN = canlib.ChannelData(self.__channel).card_upc_no
        return 'Using {:s}, EAN: {:s}'.format(chdataname, str(chdata_EAN))

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if isinstance(exception_value, KeyboardInterrupt):
            self.logger.warning('Received Ctrl+C event (KeyboardInterrupt).')
        self.closeConnection()
        removeAllHandlers(self.logger)
        removeAllHandlers(self.canLogger)
        if isinstance(exception_value, KeyboardInterrupt):
            return True

    def closeConnection(self):
        """Convenience function for closing a connection."""
        self.__ch.busOff()
        self.__ch.close()
        self.logger.info('Connection closed')

    def openConnection(self):
        """Convenience function for going on the bus."""
        self.__ch = self.cl.openChannel(self.__channel,
                                        canlib.canOPEN_ACCEPT_VIRTUAL)
        self.__ch.setBusParams(self.__bitrate)
        self.__ch.BusOn()

    @property
    def channel(self):
        """Currently used CAN channel"""
        return self.__channel

    @channel.setter
    def channel(self, channel):
        self.__channel = channel

    @property
    def bitRate(self):
        """Currently used bit rate"""
        return self.__bitrate

    @bitRate.setter
    def bitRate(self, bitrate):
        self.__bitrate = bitrate

    @property
    def nodeId(self):
        """Currently used simulated node id"""
        return self.__nodeId

    @nodeId.setter
    def nodeId(self, nodeId):
        self.__nodeId = nodeId
        self.__allowedNodeIds = self.calcAllowedNodeIds(nodeId)

    @property
    def allowedNodeIds(self):
        """Currently set node ids for message reception"""
        return self.__allowedNodeIds

    def dumpMessage(self, cobid, msg, dlc, flag, time):
        """Print a CAN message to the screen

        Parameters
        ----------
        cobid : :obj:`int`
            CAN identifier
        msg : :obj:`bytes`
            CAN data - max length 8
        dlc : :obj:`int`
            Data Length Code
        flag : :obj:`int`
            Flags, a combination of the canMSG_xxx and canMSGERR_xxx values
        time : :obj:`float`
            Timestamp from hardware
        """

        if (flag & canlib.canMSG_ERROR_FRAME != 0):
            self.logger.error("***ERROR FRAME RECEIVED***")
            self.canLogger.error("***ERROR FRAME RECEIVED***")
        else:
            msgstr = '{:3x} {:d}   '.format(cobid, dlc)
            for i in range(len(msg)):
                msgstr += '{:02x}  '.format(msg[i])
            msgstr += '    ' * (8 - len(msg)) + \
                str(timedelta(milliseconds=time))
            self.logger.info(coc.MSGHEADER)
            self.logger.info(msgstr)
            self.canLogger.info(msgstr)

    def mainloop(self):
        """Read incoming messages from the Bus and pass them to the evalation
        function. Only aborts when a CAN error occurs.
        """

        finished = False
        self.logger.debug('Entering main loop')
        self.logger.debug('This is a debug message!')
        while not finished:
            try:
                cobid, msg, dlc, flag, time = self.__ch.read(1000)
                hasMessage = True
                while hasMessage:
                    self.dumpMessage(cobid, msg, dlc, flag, time)
                    self.evaluate_message(cobid, msg, dlc, flag, time)
                    try:
                        cobid, msg, dlc, flag, time = self.__ch.read(1000)
                    except(canlib.canNoMsg):
                        hasMessage = False
                    except (canlib.canError) as ex:
                        self.logger.error(ex)
                        finished = True
            except(canlib.canNoMsg):
                pass
            except (canlib.canError) as ex:
                self.logger.exception(ex)
                finished = True
        self.logger.notice('Exiting main loop')

    def evaluate_message(self, cobid, msg, dlc, flag, time):
        """Evaluate a CANopen message for this node

        This methods decides what to do with a recieved CAN message. Depending
        on the message content a subroutine may be called for processing the
        message.

        Parameters
        ----------
        cobid : :obj:`int`
            CAN identifier
        msg : :obj:`bytes`
            CAN data - max length 8
        dlc : :obj:`int`
            Data Length Code
        flag : :obj:`int`
            Flags, a combination of the canMSG_xxx and canMSGERR_xxx values
        time : :obj:`float`
            Timestamp from hardware
        """

        # Check for error frame
        if (flag & canlib.canMSG_ERROR_FRAME != 0):
            self.logger.error("***ERROR FRAME RECEIVED***")
        # Check for NMT master command
        elif cobid == 0 and msg[1] in [0, self.__nodeId]:
            if msg[0] == 1:
                self.logger.info('Received \'start_remote_node\' command')
        # Check for SYNC message
        elif cobid == 0x80 and len(msg) == 0 and \
                (flag & canlib.canMSG_RTR == 0):
            self.logger.info('Received SYNC message')
            self.process_sync()
        # Check for node guarding
        elif cobid == 0x700 + self.__nodeId and \
                (flag & canlib.canMSG_RTR != 0):
            self.logger.info('Got node guarding message')
            self.__toggleBit = not self.__toggleBit
            self.__ch.write(0x700 + self.__nodeId,
                            [(self.__toggleBit << 7) | self.__state])
        # Check for TPDO2 request
        elif cobid == 0x280 + self.__nodeId and \
                (flag & canlib.canMSG_RTR != 0):
            self.logger.info('Received RTR for TPDO2')
        # Check for SDOtx request
        elif (cobid == coc.COBID.SDO_RX.value + self.__nodeId) and \
                ((msg[0] >> 5) == 2):
            self.logger.info('Received a SDO read request')
            self.process_sdo_read(msg)
        # Check for SDOrx request
        elif (cobid == coc.COBID.SDO_RX.value + self.__nodeId) and \
                ((msg[0] >> 5) == 1):
            self.logger.info('Received a SDO write request')
            self.process_sdo_write(msg)
        # When it is not a valid request then the command specifier is invalid.
        elif cobid == coc.COBID.SDO_RX.value + self.__nodeId:
            self.logger.error('Unkown command specifier')
            ret = self.sdo_abort_message([msg[2], msg[1]], msg[3],
                                         SAC.COMMAND)
            self.__ch.write(coc.COBID.SDO_TX.value, ret)
        # Other COB-IDs are ignored.
        else:
            self.logger.info('Got message which was not relevant for me')

    def gather_value(self, index, subindex):
        """Simulate collecting a value from hardware or from OD

        Values are created randomly according to their data type and (in case
        of PSPP registers) allowed values.

        Parameters
        ----------
        index : :obj:`int`
            Index of the OD entry
        subindex : :obj:`int`
            Subindex of the OD entry. Should be zero for single value entries

        Raises
        ------
        ChipNotConnectedError
            When a PSPP is not connected
        """
        if index in range(0x2200, 0x2240):
            if subindex != 2 and not self.__od[index][2]:
                raise ChipNotConnectedError
            # Register values
            if subindex in range(0x10, 0x1D):
                # sleep(0.001)
                return rdm.randrange(PSPP_MAX_VALUES[subindex - 0x10])
            # ADC channels
            if subindex in range(0x20, 0x28):
                # sleep(0.001)
                return (subindex - 0x20) * 8192 + rdm.randrange(1024)
            # Monitoring data
            if subindex == 1:
                # sleep(0.005)
                t = (2**9 + rdm.randrange(2**5)) << 20
                v1 = (2**9 + rdm.randrange(2**5)) << 10
                v2 = 2**9 + rdm.randrange(2**5)
                return (1 << 31) | t | v1 | v2
        elif index == 0x2300 and subindex in range(1, 4):
            return subindex * 8192 + rdm.randrange(256)
        return self.__od[index][subindex].value

    def process_sdo_read(self, msg, timeout=42):
        """Process an SDO read request

        Currently expedited and segmented transfer is supported. Error checks
        are done for existence of (sub)index.

        Parameters
        ----------
        msg : :obj:`list` of :obj:`int`
            CAN data. Must have a length of 8 bytes.
        timeout : :obj:`int`, optional
            SDO timeout in milliseconds

        Returns
        -------
        bool
            If the SDO read service has been executed correctly including data
            transfer.
        """

        # Initialize variables and parameters
        index = int.from_bytes([msg[1], msg[2]], 'little')
        idx = [0, 0]
        idx[0], idx[1] = index.to_bytes(2, 'little')
        subindex = msg[3]
        ret = [0 for i in range(coc.MAX_DATABYTES)]
        cobid = coc.COBID.SDO_TX + self.__nodeId
        ret[1], ret[2] = msg[1], msg[2]
        ret[3] = msg[3]
        # Check for SDO read request
        if msg[0] == 0x40:
            # Check if object exists
            if index not in self.__od or index == 0x2100:
                ret = self.sdo_abort_message(idx, subindex, SAC.NO_OBJECT)
                self.__ch.writeWait(Frame(cobid, ret), timeout)
                self.logger.error('Object for SDO transfer does not exist!')
                return False
            elif subindex not in self.__od[index]:
                ret = self.sdo_abort_message(idx, subindex, SAC.SUBINDEX)
                self.__ch.writeWait(Frame(cobid, ret), timeout)
                self.logger.error('Subindex for SDO transfer does not exist!')
                return False
            try:
                val = self.gather_value(index, subindex)
                self.logger.info(f'Answering with value {val:X}.')
            except ChipNotConnectedError:
                ret = self.sdo_abort_message(idx, subindex, SAC.HARDWARE_ERROR)
                self.__ch.writeWait(Frame(cobid, ret), timeout)
                self.logger.error('The PSPP to read from is not connected!')
                return False
            byteval, datasize = self.parse_val(val)
            # Expedited transfer
            if len(byteval) == 4:
                self.logger.info('Using expedited transfer for response.')
                ret[4], ret[5], ret[6], ret[7] = byteval
                ret[0] = (((0b0100 << 2) | ((4 - datasize) & 0b11)) << 2) | \
                    0b11
                self.__ch.writeWait(Frame(cobid, ret), timeout)
                return True
            # Segmented transfer
            else:
                self.logger.error('Segmented transfer not implemented!')
                return False
        elif msg[0] == 0x80:
            self.logger.error('Received SDO abort message!')
            return False
        else:
            self.logger.error('Unknown SDO command specifier in initial '
                              'request (0x{:02x})'.format(msg[0]))
            ret = self.sdo_abort_message(idx, subindex, SAC.COMMAND)
            self.__ch.writeWait(Frame(cobid, ret), timeout)
            return False

    def process_sdo_write(self, msg, timeout=42):
        """Process a SDO write request.

        Abort transfer if not expedited.

        Parameters
        ----------
        msg : :obj:`list` of :obj:`int`
            CAN data. Must have a length of 8 bytes.
        timeout : :obj:`int`, optional
            SDO timeout in milliseconds
        """

        cmd = msg[0]
        index = int.from_bytes([msg[1], msg[2]], 'little')
        subindex = msg[3]
        n = (cmd >> 2) & 0b11
        datasize = 4 - n
        data = int.from_bytes(msg[4:(4 + datasize)], 'little')
        cobid = coc.COBID.SDO_TX + self.__nodeId
        ret = [0 for i in range(8)]
        # Check if command specifier known
        if cmd not in [0x23, 0x27, 0x2b, 0x2f]:
            self.logger.error('Unkown command specifier')
            ret = self.sdo_abort_message([msg[2], msg[1]], msg[3],
                                         SAC.COMMAND)
        # Check if object exists
        elif index not in self.__od:
            self.logger.error('Object does not exist.')
            ret = self.sdo_abort_message([msg[2], msg[1]], msg[3],
                                         SAC.NO_OBJECT)
        # Check if subindex exists
        elif subindex not in self.__od[index]:
            self.logger.error('Subindex does not exist.')
            ret = self.sdo_abort_message([msg[2], msg[1]], msg[3],
                                         SAC.SUBINDEX)
        # Check access attribute
        elif self.__od[index][subindex].attribute in [coc.ATTR.RO,
                                                      coc.ATTR.CONST]:
            self.logger.error('No write access')
            ret = self.sdo_abort_message([msg[2], msg[1]], msg[3],
                                         SAC.ACCESS)
        else:
            self.logger.debug(f'Writing value {data:X} on '
                              f'{index:X}:{subindex:X}.')
            self.__od[index][subindex].value = data
            ret[0] = 0x60
            ret[1:4] = msg[1:4]
            ret[4:] = [0 for i in range(4)]
            if index == 0x2000 and subindex in range(1, 5):
                scb = subindex - 1
                self.logger.notice(f'SCB{scb}: Setting connections.')
                for i in range(16):
                    pspp_idx = 0x2200 + scb * 16 + i
                    self.__od[pspp_idx][2].value = bool((data >> i) & 1)
        self.__ch.writeWait(Frame(cobid, ret), timeout)

    def sdo_abort_message(self, index, subindex, abort_code):
        """Calculate message bytes for SDO error message

        The first byte (:obj:`0x80`) indicates a SDO abort message.

        Parameters
        ----------
        index
            The main index as byte-like object of length two with byteorder
            'little'.
        subindex : :obj:`int`
            The subindex of an specified OD object
        abort_code : :obj:`int` or :obj:`CANopenConstants.sdoAbortCode`
            SDO abort code (32 bit)

        Returns
        -------
        :obj:`list` of :obj:`int`
            The message bytes as a list of integers
        """
        if isinstance(abort_code, SAC):
            ac = abort_code.value.to_bytes(4, 'little')
        elif isinstance(abort_code, int):
            ac = abort_code.to_bytes(4, 'little')
        else:
            raise ValueError('Abort code has inappropiate type')
        ret = [0 for i in range(8)]
        ret[0] = 0b10000000
        ret[1], ret[2] = index[0], index[1]
        ret[3] = subindex
        ret[4], ret[5], ret[6], ret[7] = ac
        return ret

    def process_sync(self):
        """React to a SYNC message

        Simulate read out of PSPPs and send data as several PDOs.
        """

        # Gather number and position connected chips
        n_PSPP = [bin(x.value).count('1') for x in self.__od[0x2000][1:]]
        p_PSPP = [[i for i in range(16) if format(x.value, '016b')[i] == '1']
                  for x in self.__od[0x2000][1:]]
        self.logger.debug('Number of connected PSPP per SCB: ' + str(n_PSPP))
        self.logger.debug('Position of connected PSPP per SCB: ' + str(p_PSPP))

        # Initialize variables
        cobid = coc.COBID.TPDO1.value + self.__nodeId
        msg = [0 for i in range(6)]

        # Transmit monitoring values of the Controller
        self.logger.debug('Transmit monitoring values of Controller')
        msg[0] = 0x80
        msg[1:5] = [rdm.randrange(256) for i in range(4)]
        self.__ch.write(cobid, msg)

        # Transmit monitoring values of PSPPs
        self.logger.debug('Transmit monitoring values of PSPPs')
        for scb in range(4):
            for i in range(n_PSPP[scb]):
                sleep(0.005)    # Simulate communication with hardware
                msg[0] = (scb << 4) | p_PSPP[scb][i]
                msg[1:] = (((1 << 38) | rdm.randrange(2**38)) <<
                           1).to_bytes(5, 'little')
                self.__ch.write(cobid, msg)

    def parse_val(self, val):
        """Convert a value to a byte array.

        The byte array will be at least four bytes long. When there is not
        enough data, bytes conatining zero will be added. Currently only
        strings and integers can be parsed.

        Parameters
        ----------
        val
            The value which shall be converted

        Returns
        -------
        :obj:`bytes`
            Data bytes
        :obj:`int`
            Data size
        """
        ret = None
        if isinstance(val, str):
            dz = len(val)
            ret = b''.join([bytearray(val, 'ascii'),
                            bytearray(max(0, 4 - len(val)))])
        elif isinstance(val, int):
            vbl = val.bit_length()
            dz = ceil(vbl / 8)
            ret = val.to_bytes(max(4, dz), 'little')
        else:
            self.logger.error('No data types beside string and int supported!')
        return ret, dz


def main():
    """Wrapper function for use as a command line tool"""

    # Parse arguments
    parser = ArgumentParser(description='Python simulation of DCS Controller',
                            epilog='For more information contact '
                                   'sebastian.scholz@cern.ch')
    parser.add_argument('-n', '--nodeId', metavar='NODEID', type=int,
                        help='CAN node id of this simulated DCS Controller')
    parser.add_argument('-c', '--channel', metavar='CHANNEL', type=int,
                        help='Number of CAN channel to use')
    parser.add_argument('-l', '--loglevel', metavar='LOGLEVEL',
                        help='Level of console logging')
    parser.add_argument('-v', '--version', action='version',
                        version='0.1.0')
    args = parser.parse_args()

    # Start the server
    with CANopenDCSController(**vars(args)) as codc:
        codc.mainloop()


if __name__ == '__main__':

    with CANopenDCSController(loglevel=logging.NOTICE) as codc:
        codc.mainloop()
