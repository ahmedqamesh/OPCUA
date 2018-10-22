#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
This module provides a class for an |OPCUA|__ server for the |DCS| Controller.

It also provides a function for using this server as a command line tool.

Note
----
If you want to use a virtual channel on a Linux machine you have to may have to
start it manually with the following command::

    $ sudo /usr/sbin/virtualcan.sh start


:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal

.. __: `OPC UA`_
"""
# Standard library modules
import os
import logging
from logging.handlers import RotatingFileHandler
import random as rdm
import time
# from datetime import timedelta
from argparse import ArgumentParser

# Third party modules
import coloredlogs as cl
import verboselogs
from canlib import canlib, Frame
from opcua import Server, ua
import analib

# Other files
try:
    from .objectDictionary import objectDictionary
    from . import CANopenConstants as coc
    from .mirrorClasses import MyDCSController
    from .extend_logging import extend_logging, removeAllHandlers
except (ModuleNotFoundError, ImportError):
    from objectDictionary import objectDictionary
    import CANopenConstants as coc
    from mirrorClasses import MyDCSController
    from extend_logging import extend_logging, removeAllHandlers


class BusEmptyError(Exception):
    pass


class DCSControllerServer(object):
    """|OPCUA| server for |DCS| Controllers in a |CAN| network.

    Establishes communication with |DCS| Controllers on a |CAN| bus and create
    corresponding |OPCUA| objects. The |CAN| communication is started during
    initialization but the |OPCUA| server has to be started separatly.

    The Initialization does several things in the following order:

    * Initialize logging
    * Configure |OPCUA| server
    * Import |OPCUA| Objects Types from |XML|
    * Configure and open |CAN| channel
    * Import Object Dictionary from |EDS|

    Parameters
    ----------
    interface : {'Kvaser', 'AnaGate'}
        Vendor of the |CAN| interface.
    edsfile : :obj:`str`, optional
        File path of |EDS|. The default will search for
        'CANControllerForPSPPv1.eds' in the directory of this file.
    console_loglevel : :obj:`int` or :obj:`str`, optional
        Defines which log messages are displayed in the console.
    file_loglevel : :obj:`int` or :obj:`str`, optional
        Defines which log messages are written to the logfiles.
    channel : :obj:`int`, optional
        Number of the |CAN| port to be used.
    logformat : :obj:`str`, optional
        Defines formatting of log messages. Defaults to a compact form
        containing only time, levelname and message.
    endpoint : :obj:`str`, optional
        Endpoint of the |OPCUA| server. Defaults to
        'opc.tcp://localhost:4840/'
    bitrate : :obj:`int`, optional
        |CAN| bitrate to be used. The default value (:data:`None`) correponds
        to a frequency of 125 kHz.
    xmlfile : :obj:`str`, optional
        File name or path of |OPCUA| model design file. The default searches
        `'dcscontrollerdesign.xml'` in the directory of this file.
    ipAddress : :obj:`str`, optional
        Network address of the AnaGate partner. Defaults to ``'192.168.1.254'``
        which is the factory default.

    Example
    -------
    You may use the commandline tool which is created on installation or you
    can start the server from python script with a few simple lines.

    >>> from dcsControllerServer import DCSControllerServer
    >>> with DCSControllerServer() as server:
    >>>     server.start()

    Notes
    -----
    I recommended that this class is initialized within a :keyword:`with`
    statement to make use of the :meth:`~contextmanager.__enter__` and
    :meth:`~contextmanager.__exit__` methods so that all open connections get
    cleaned up in case of errors.
    """

    def __init__(self, interface='Kvaser', edsfile=None,
                 console_loglevel=logging.NOTICE,
                 logformat='%(asctime)s %(levelname)-8s %(message)s',
                 endpoint='opc.tcp://localhost:4840/',
                 file_loglevel=logging.INFO, channel=0,
                 bitrate=None, xmlfile=None,
                 ipAddress='192.168.1.254'):

        self.__isinit = False
        self.ret = None

        # Initialize logger
        extend_logging()
        verboselogs.install()
        self.logger = logging.getLogger(__name__)
        """:obj:`~logging.Logger`: Main logger for this class"""
        self.logger.setLevel(logging.DEBUG)
        self.opcua_logger = logging.getLogger('opcua')
        self.opcua_logger.setLevel(logging.WARNING)
        scrdir = os.path.dirname(os.path.abspath(__file__))
        ts = os.path.join(scrdir, 'log',
                          time.strftime('%Y-%m-%d_%H-%M-%S_OPCUA_Server.'))
        self.__fh = RotatingFileHandler(ts + 'log', backupCount=10,
                                        maxBytes=10 * 1024 * 1024)
        fmt = logging.Formatter(logformat)
        self.__fh.setFormatter(fmt)
        cl.install(fmt=logformat, level=console_loglevel, isatty=True)
        self.__fh.setLevel(file_loglevel)
        self.logger.addHandler(self.__fh)
        self.__fh_opcua = RotatingFileHandler(ts + 'opcua.log', backupCount=10,
                                              maxBytes=10 * 1024 * 1024)
        self.__fh_opcua.setFormatter(fmt)
        self.__fh_opcua.setLevel(file_loglevel)
        self.opcua_logger.addHandler(self.__fh_opcua)
        self.logger.info(f'Existing logging Handler: {self.logger.handlers}')

        # Initialize default arguments
        if interface not in ['Kvaser', 'AnaGate']:
            raise ValueError(f'Possible CAN interfaces are "Kvaser" or '
                             f'"AnaGate" and not "{interface}".')
        self.__interface = interface
        if bitrate is None:
            if interface == 'Kvaser':
                bitrate = canlib.canBITRATE_125K
            else:
                bitrate = 125000

        # Initialize OPC server
        self.logger.notice('Configuring OPC UA server ...')
        self.server = Server()
        """:doc:`opcua.Server<server>` : Handles the |OPCUA| server."""
        self.__isserver = False
        """:obj:`bool` : If the server is currently running"""
        self.__endpoint = endpoint
        self.server.set_endpoint(endpoint)
        # self.server.allow_remote_admin(True)

        # Setup our own namespace, not really necessary but should as spec
        self.logger.info('Configuring namespace')
        uri = "http://yourorganisation.org/DCSControllerDesign/"
        self.__idx = self.server.register_namespace(uri)
        """:obj:`int` : Index of the registered custom namespace"""
        self.logger.info('Namespace index: ' + str(self.__idx))
        self.logger.success('... Done!')

        # Import objects
        self.logger.notice('Importing OPCUA object types from XML. This may '
                           'take some time ...')
        scrdir = os.path.dirname(os.path.abspath(__file__))
        if xmlfile is None:
            xmlfile = os.path.join(scrdir, 'dcscontrollerdesign.xml')
        self.server.import_xml(xmlfile)
        self.logger.success('... Done!')

        # Get Objects node, this is where we should put our custom stuff
        self.__objects = self.server.get_objects_node()

        # Initialize library and set connection parameters
        self.__busOn = False
        """:obj:`bool` : If communication is established"""
        self.__channel = channel
        """:obj:`int` : Internal attribute for the channel index"""
        self.__bitrate = bitrate
        """:obj:`int` : Internal attribute for the bit rate"""
        self.__ch = None
        """Internal attribute for the |CAN| channel"""
        if interface == 'Kvaser':
            self.__ch = canlib.openChannel(channel,
                                           canlib.canOPEN_ACCEPT_VIRTUAL)
            self.__ch.setBusParams(self.__bitrate)
            self.logger.notice('Going in \'Bus On\' state ...')
            self.__ch.busOn()
        else:
            self.__ch = analib.Channel(ipAddress, channel, baudrate=bitrate)
        self.logger.success(str(self))
        self.__busOn = True

        # Get DCS Controller OPC UA Object Type
        self.logger.notice('Get OPC UA Object Type of DCS Controller ...')
        self.__dctni = ua.NodeId.from_string(f'ns={self.__idx};i=1003')
        """|OPCUA| Object Type of |DCS| Controller"""
        self.logger.success('... Done!')

        # Scan nodes
        self.__nodeIds = []
        """:obj:`list` of :obj:`int` : Contains all |CAN| nodeIds currently
        present on the bus."""
        self.__myDCs = {}
        """:obj:`list` : |OPCUA| Object representation of all |DCS| Controllers
        that are currently on the |CAN| bus"""
        self.__mypyDCs = {}
        """:obj:`dict` : List of :class:`MyDCSController` instances which
        mirrors |OPCUA| adress space. Key is the node id."""

        # Import Object Dictionary from EDS
        self.logger.notice('Importing Object Dictionary ...')
        if edsfile is None:
            self.logger.debug('File path for EDS not given. Looking in '
                              'the dicrectory of this script.')
            edsfile = os.path.join(scrdir, 'CANControllerForPSPPv1.eds')
        self.__od = objectDictionary.from_eds(self.logger, edsfile, 0)
        """:class:`~.objectDictionary.objectDictionary` : The CANopen Object
        Dictionary (|OD|) for a |DCS| Controller"""

    def __str__(self):
        if self.__interface == 'Kvaser':
            chdataname = canlib.ChannelData(self.__channel).device_name
            chdata_EAN = canlib.ChannelData(self.__channel).card_upc_no
            return f'Using {chdataname}, EAN: {chdata_EAN}, Port: ' \
                f'{self.endpoint}.'
        else:
            return f'{self.__ch}'

    __repr__ = __str__

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if exception_type is KeyboardInterrupt:
            self.logger.warning('Received Ctrl+C event (KeyboardInterrupt).')
        self.__fh.close()
        self.__fh_opcua.close()
        removeAllHandlers(self.logger)
        removeAllHandlers(self.opcua_logger)
        self.stop()
        if exception_type is KeyboardInterrupt:
            return True
        else:
            self.logger.exception(exception_value)
            return True

    @property
    def channel(self):
        """:obj:`int` : Currently used |CAN| channel."""
        return self.__channel

    @property
    def bitRate(self):
        """:obj:`int` : Currently used bit rate. When you try to change it
        :func:`stop` will be called before."""
        if self.__interface == 'Kvaser':
            return self.__bitrate
        else:
            return self.__ch.baudrate

    @bitRate.setter
    def bitRate(self, bitrate):
        if self.__interface == 'Kvaser':
            self.stop()
            self.__bitrate = bitrate
            self.start()
        else:
            self.__ch.baudrate = bitrate

    @property
    def endpoint(self):
        """:obj:`str` : Port where the server is listening to"""
        return self.__endpoint

    @property
    def mypyDCs(self):
        """:obj:`dict`: Dictionary containing |DCS| Controller mirror classes.
        Key is the CANopen node id."""
        return self.__mypyDCs

    @property
    def idx(self):
        """:obj:`int` : Index of custom namespace"""
        return self.__idx

    @property
    def myDCs(self):
        """:obj:`list` : List of created UA objects"""
        return self.__myDCs

    @property
    def isinit(self):
        """:obj:`bool` : If all initialization routines have been executed"""
        return self.__isinit

    @property
    def od(self):
        """:class:`~dcsControllerServer.objectDictionary.objectDictionary` :
        Object dictionary for checking access attributes"""
        return self.__od

    @property
    def interface(self):
        """:obj:`str` : Vendor of the CAN interface. Possible values are
        ``'Kvaser'`` and ``'AnaGate'``."""
        return self.__interface

    @property
    def ipAddress(self):
        """:obj:`str` : Network address of the AnaGate partner. Only used for
        AnaGate CAN interfaces."""
        if self.__interface == 'Kvaser':
            raise AttributeError('You are using a Kvaser CAN interface!')
        return self.__ch.ipAddress

    def start(self):
        """Start the server and open the |CAN| connection

        Make sure that this is called so that the connection is established.

        Steps:

        * Open |CAN| channel
        * Scan |CAN| bus for nodes (and create UA objects)
        * Start the actual |OPCUA| server
        * Create python objects mirroring the UA address space
        * Start the main :func:`run` routine

        This method has a small error tolerance and restarts 2 two times in
        case of errors.
        """

        count = 0
        while count < 3:
            try:
                if self.__interface == 'Kvaser':
                    self.logger.notice('Opening CAN channel ...')
                    self.__ch = canlib.openChannel(self.__channel,
                                                   canlib.canOPEN_ACCEPT_VIRTUAL)
                    self.logger.info(str(self))
                    self.__ch.setBusParams(self.__bitrate)
                    if not self.__busOn:
                        self.logger.notice('Going in \'Bus On\' state ...')
                        self.__busOn = True
                    self.__ch.busOn()
                else:
                    if not self.__ch.deviceOpen:
                        self.logger.notice('Reopening AnaGate CAN interface')
                        self.__ch.openChannel()
                    if self.__ch.state != 'CONNECTED':
                        self.logger.notice('Restarting AnaGate CAN interface.')
                        self.__ch.restart()
                        time.sleep(10)
                self.scanNodes()
                if len(self.__nodeIds) == 0:
                    raise BusEmptyError('No CAN nodes found!')
                self.logger.notice('Starting the server ...')
                self.server.start()
                self.__isserver = True
                self.createMirroredObjects()
                time.sleep(1)
                self.__isinit = True
                # Do not do this if you have auto-detection of your PSPPs
                # self.rdmSetConnPSPP()
                # Do this instead
                for nodeId in self.__nodeIds:
                    self.mypyDCs[nodeId].Status = True
                self.logger.success('Initialization Done.')
                self.run()
            except BusEmptyError as ex:
                self.__isinit = False
                self.logger.error(ex)
                self.stop()
                self.logger.notice('Restarting in 60 seconds ...')
                time.sleep(60)
            except Exception as ex:
                self.__isinit = False
                self.logger.exception(ex)
                self.stop()
                self.logger.notice('Restarting in 10 seconds ...')
                time.sleep(10)
                count += 1
        else:
            self.logger.critical('The third try failed. Exiting.')

    def stop(self):
        """Close |CAN| channel and stop the |OPCUA| server

        Make sure that this is called so that the connection is closed in a
        correct manner. When this class is used within a :obj:`with` statement
        this method is called automatically when the statement is exited.
        """
        if self.__busOn:
            if self.__interface == 'Kvaser':
                self.logger.warning('Going in \'Bus Off\' state.')
                self.__ch.busOff()
            self.__busOn = False
            self.logger.warning('Closing the CAN channel.')
            self.__ch.close()
        self.logger.warning('Stopping the server.')
        try:
            self.server.stop()
        except AttributeError:
            pass
        self.__isserver = False

    def run(self):
        """Start actual CANopen communication"""

        count = 0
        while True:
            count = 0 if count == 10 else count
            # Loop over all connected CAN nodeIds
            for nodeId in self.__nodeIds:
                ret = self.mypyDCs[nodeId].Status
                self.logger.debug(f'Controller{nodeId}.Status = {ret}')
                # Loop over all SCB masters
                for scb in range(4):
                    exec(f'self.ret = self.mypyDCs[nodeId].SCB{scb}.'
                         'ConnectedPSPPs')
                    cp = [i for i in range(16)
                          if int(f'{self.ret:016b}'[::-1][i])]
                    if self.ret is not None:
                        self.logger.debug(f'Connected PSPPs: {self.ret}')
                    # Loop over all possible PSPPs
                    for pspp in cp:
                        # Loop over PSPP monitoring data
                        exec(f'self.ret = self.mypyDCs[nodeId].SCB{scb}.'
                             f'PSPP{pspp}.MonitoringData.Temperature')
                        if self.ret is not None:
                            self.logger.debug(f'SCB{scb}.PSPP{pspp}.MonVals = '
                                          f'{self.ret:X}')
                        # Read less often than monitoring values
                        if count == 0:
                            exec(f'self.ret = self.mypyDCs[nodeId].SCB{scb}.'
                                 f'PSPP{pspp}.Status')
                            # Loop over ADC channels
                            for ch in range(8):
                                exec(f'self.ret = self.mypyDCs[nodeId].'
                                     f'SCB{scb}.PSPP{pspp}.ADCChannels.Ch{ch}')
                            # Loop over registers
                            for name in coc.PSPP_REGISTERS:
                                exec(f'self.ret = self.mypyDCs[nodeId].'
                                     f'SCB{scb}.PSPP{pspp}.Regs.{name}')
                            count = 0   # Reset to avoid overflow
            count += 1
            # time.sleep(60)

    def dumpMessage(self, cobid, msg, dlc, flag):
        """Dumps a CANopen message to the screen and log file

        Parameters
        ----------
        cobid : :obj:`int`
            |CAN| identifier
        msg : :obj:`bytes`
            |CAN| data - max length 8
        dlc : :obj:`int`
            Data Length Code
        flag : :obj:`int`
            Flags, a combination of the :const:`canMSG_xxx` and
            :const:`canMSGERR_xxx` values
        """

        if (flag & canlib.canMSG_ERROR_FRAME != 0):
            self.logger.error("***ERROR FRAME RECEIVED***")
        else:
            msgstr = '{:3X} {:d}   '.format(cobid, dlc)
            for i in range(len(msg)):
                msgstr += '{:02x}  '.format(msg[i])
            msgstr += '    ' * (8 - len(msg))
            self.logger.info(coc.MSGHEADER)
            self.logger.info(msgstr)

    def writeMessage(self, cobid, msg, flag=0, timeout=10):
        """Combining writing functions for different |CAN| interfaces

        Parameters
        ----------
        cobid : :obj:`int`
            |CAN| identifier
        msg : :obj:`list` of :obj:`int` or :obj:`bytes`
            Data bytes
        flag : :obj:`int`, optional
            Message flag (|RTR|, etc.). Defaults to zero.
        timeout : :obj:`int`, optional
            |SDO| write timeout in milliseconds. Defaults to 10 ms.
        """
        if self.__interface == 'Kvaser':
            self.__ch.writeWait(Frame(cobid, msg), timeout)
        else:
            self.__ch.write(cobid, msg, flag)

    def readMessage(self, timeout):
        """Combining different reading functions for |CAN| interfaces

        Parameters
        ----------
        timeout : :obj:`int`
            |SDO| timeout in milliseconds

        Raises
        ------
        :exc:`CanNoMsg`
            No new |CAN| message has arrived and the timeout has expired. The
            exception comes from :mod:`canlib` or :mod:`analib` depending on
            the used interface.
        """
        if self.__interface == 'Kvaser':
            return self.__ch.read(timeout)
        else:
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < timeout / 1000:
                try:
                    cobid, data, dlc, flag, t = self.__ch.getMessage()
                    return cobid, data, dlc, flag, t
                except analib.CanNoMsg:
                    pass
            raise analib.CanNoMsg

    def sdoRead(self, nodeId, index, subindex, timeout=42):
        """Read an object via |SDO|

        Currently expedited and segmented transfer is supported by this method.
        The user has to decide how to decode the data.

        Parameters
        ----------
        nodeId : :obj:`int`
            The id from the node to read from
        index : :obj:`int`
            The Object Dictionary index to read from
        subindex : :obj:`int`
            |OD| Subindex. Defaults to zero for single value entries.
        timeout : :obj:`int`, optional
            |SDO| timeout in milliseconds

        Returns
        -------
        :obj:`list` of :obj:`int`
            The data if was successfully read
        :data:`None`
            In case of errors
        """
        if nodeId is None or index is None or subindex is None:
            self.logger.warning('SDO read protocol cancelled before it could '
                                'begin.')
            return None
        self.logger.info(f'Send SDO read request to node {nodeId}.')
        cobid = coc.COBID.SDO_RX + nodeId
        msg = [0 for i in range(coc.MAX_DATABYTES)]
        msg[1], msg[2] = index.to_bytes(2, 'little')
        msg[3] = subindex
        msg[0] = 0x40
        self.writeMessage(cobid, msg, timeout=timeout)
        # Wait for response
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout / 1000:
            try:
                cobid_ret, ret, dlc, flag, t = self.readMessage(timeout)
            except (canlib.canNoMsg, analib.CanNoMsg):
                return None
            self.dumpMessage(cobid_ret, ret, dlc, flag)
            if int.from_bytes([ret[1], ret[2]], 'little') == index and \
                    ret[3] == subindex:
                break
        # Check command byte
        datasize_indicated = (ret[0] & 0b1) == 1
        expedited = ((ret[0] >> 1) & 0b1) == 1
        segmented = not expedited
        databytes = 4 - ((ret[0] >> 2) & 0b11)
        scs = ret[0] >> 4
        retindex = int.from_bytes([ret[1], ret[2]], 'little')
        retsubindex = ret[3]
        if retindex != index:
            self.logger.warning(f'Got wrong return index: {retindex:X} instead'
                                f' of {index:X}')
            return None
        if retsubindex != subindex:
            self.logger.warning(f'Got wrong return subindex: {retsubindex:X} '
                              f'instead of {subindex:X}')
            return None
        if scs == 0b0100 and not datasize_indicated:
            self.logger.error('Datasize not indicated')
            return None
        if scs == 0b0100:
            data = []
            if expedited:
                for i in range(databytes):
                    data.append(ret[4 + i])
            elif segmented:
                self.logger.error('Segmented transfer not implemented!')
                return None
            self.logger.info(f'Got data: {data}')
            return data
        elif ret[0] == 0x80:
            self.logger.error('Received SDO abort message')
        else:
            self.logger.error('Invalid SDO command specifier')
        return None

    def sdoWrite(self, nodeId, index, subindex, value, timeout=100):
        """Write an object via |SDO| expedited write protocol

        This sends the request and analyses the response.

        Parameters
        ----------
        nodeId : :obj:`int`
            The id from the node to read from
        index : :obj:`int`
            The |OD| index to read from
        subindex : :obj:`int`
            Subindex. Defaults to zero for single value entries
        value : :obj:`int`
            The value you want to write.
        timeout : :obj:`int`, optional
            |SDO| timeout in milliseconds

        Returns
        -------
        :obj:`bool`
            If writing the object was successful
        """

        # Create the request message
        self.logger.info(f'Send SDO write request to node {nodeId}.')
        self.logger.info(f'Writing value {value:X}')
        cobid = coc.COBID.SDO_RX + nodeId
        datasize = len(f'{value:X}') // 2 + 1
        data = value.to_bytes(4, 'little')
        msg = [0 for i in range(8)]
        msg[0] = (((0b00010 << 2) | (4 - datasize)) << 2) | 0b11
        msg[1], msg[2] = index.to_bytes(2, 'little')
        msg[3] = subindex
        msg[4:] = [data[i] for i in range(4)]
        # Send the request message
        self.writeMessage(cobid, msg, timeout=timeout)

        # Read the response from the bus
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout / 1000:
            try:
                cobid_ret, ret, dlc, flag, t = self.readMessage(timeout)
            except (canlib.canNoMsg, analib.CanNoMsg):
                return False
            self.dumpMessage(cobid_ret, ret, dlc, flag)
            if int.from_bytes([ret[1], ret[2]], 'little') == index and \
                    ret[3] == subindex and \
                    cobid_ret == coc.COBID.SDO_TX + nodeId:
                break
        # Analyse the response
        retindex = int.from_bytes([ret[1], ret[2]], 'little')
        retsubindex = ret[3]
        if cobid_ret != coc.COBID.SDO_TX + nodeId:
            self.logger.error(f'Got wrong COB-ID ({cobid_ret:X})')
            return False
        elif retindex != index:
            self.logger.warning(f'Got wrong return index: {retindex:X} instead'
                                f' of {index:X}')
            return False
        elif retsubindex != subindex:
            self.logger.warning(f'Got wrong return subindex: {retsubindex:X} '
                              f'instead of {subindex:X}')
            return False
        elif ret[0] == 0x80:
            abort_code = int.from_bytes(ret[4:], 'little')
            self.logger.error('Got SDO abort message. Abort code: '
                              f'{abort_code:08X}')
            return False
        elif ret[0] != 0b1100000:
            self.logger.error(f'Wrong command specifier ({ret[0]:02X})')
            return False
        else:
            self.logger.success('SDO write protocol successful!')
        return True

    def setConnectedPSPP(self, nodeId=42, data=None):
        """Set which |PSPP| chips are connected to a specified Controller

        Parameters
        ----------
        nodeId : :obj:`int`, optional
            |CAN| Node Id of the Controller. Defaults to 42.
        data : :obj:`list` of :obj:`int`, optional
            4*16 bit of information about connected |PSPP| chips. Defaults to
            :data:`None`.
        """
        self.logger.notice('Start transmitting info about connected PSPPs to '
                           'the Controller ...')
        if data is None:
            data = [rdm.randrange(2**16) for i in range(4)]
        self.logger.info('Writing data: ' + str(data))
        for scb in range(4):
            exec(f'self.mypyDCs[nodeId].SCB{scb}.ConnectedPSPPs = data[scb]')
        self.mypyDCs[nodeId].Status = True
        self.logger.success('... Done.')

    def rdmSetConnPSPP(self):
        """Wrapper function which randomly sets connected PSPPs"""
        for nodeid in self.__nodeIds:
            self.setConnectedPSPP(nodeid, [0xffff for i in range(4)])

    def scanNodes(self, timeout=42):
        """Do a complete scan over all |CAN| nodes

        The internally stored information about all nodes are reset. This
        method will be called by the :meth:`__init__` method. It should also be
        used to reestablish communication when it was lost or when a new device
        was connected while the user program is running.

        This works by reading a mandatory |OD| object with |SDO| of all nodes
        and removing those which do not respond.

        This overrides any previous configurations and empties the lists and
        dictionaries for stored objects.

        Parameters
        ----------
        timeout : :obj:`int`, optional
            |SDO| timeout in milliseconds
        """
        self.logger.notice('Scanning nodes. This will take a few seconds ...')
        self.__nodeIds = list(range(1, 128))
        self.__mypyDCs = {}
        for nodeId in range(1, 128):
            dev_t = self.sdoRead(nodeId, 0x1000, 0, timeout)
            time.sleep(timeout / 1000)
            if dev_t is None:
                self.logger.debug(f'Remove node id {nodeId}')
                self.__nodeIds.remove(nodeId)
            else:
                self.logger.success(f'Added node {nodeId}')
        self.logger.success('... Done!')

        # Populate adress space
        self.logger.notice('Creating OPCUA Objects for every Controller on the'
                           ' bus ...')
        self.__myDCs = {}
        for n in self.__nodeIds:
            self.__myDCs[n] = \
                self.__objects.add_object(self.__idx, f'DCSController{n}',
                                          self.__dctni)
        self.logger.success('... Done!')

    def createMirroredObjects(self):
        """Create mirror Classes for every UA object.

        This method sets the CANopen node id to the Controller UA objects and
        creates mirror classes that mirror the whole UA address space. Note
        that the dictionary where these classes are stored is emptied at the
        start of this methods.

        Warning
        -------
        This method must be called after the server is started and after
        the UA objects have been created.
        """
        self.logger.notice('Creating mirrored python objects for every UA '
                           'object ...')
        self.__mypyDCs = {}
        for i in self.__nodeIds:
            # self.__objects.get_child([f'{self.__idx}:DCSController{i}',
            #                          f'{self.__idx}:NodeId']).set_value(i)
            self.__myDCs[i].get_child(f'{self.__idx}:NodeId').set_value(i)
            self.__mypyDCs[i] = MyDCSController(self, self.__myDCs[i], i)
        self.logger.success('... Done!')


def main():
    """Wrapper function for using the server as a command line tool

    The command line tool accepts arguments for configuring the server which
    are tranferred to the :class:`DCSControllerServer` class.
    """

    # Parse arguments
    parser = ArgumentParser(description='OPCUA CANopen server for DCS '
                                        'Controller',
                            epilog='For more information contact '
                                   'sebastian.scholz@cern.ch')
    parser.add_argument('-i', '--interface', metavar='INTERFACE',
                        help='Vendor of the CAN interface. Possible values are'
                        ' "Kvaser" (default) and "AnaGate" (case-sensitive)',
                        default='Kvaser')
    parser.add_argument('-E', '--endpoint', metavar='ENDPOINT',
                        help='Endpoint of the OPCUA server',
                        default='opc.tcp://localhost:4840/')
    parser.add_argument('-e', '--edsfile', metavar='EDSFILE',
                        help='File path of Electronic Data Sheet (EDS)')
    parser.add_argument('-x', '--xmlfile', metavar='XMLFILE',
                        help='File path of OPCUA XML design file')
    parser.add_argument('-C', '--channel', metavar='CHANNEL', type=int,
                        help='Number of CAN channel to use', default=0)
    parser.add_argument('-c', '--console-loglevel', metavar='CONSOLE_LOGLEVEL',
                        default=logging.NOTICE, dest='console_loglevel',
                        help='Level of console logging')
    parser.add_argument('-f', '--file-loglevel', metavar='FILE_LOGLEVEL',
                        default=logging.INFO, dest='file_loglevel',
                        help='Level of file logging')
    parser.add_argument('-v', '--version', action='version',
                        version='0.1.0')
    args = parser.parse_args()

    # Start the server
    with DCSControllerServer(**vars(args)) as server:
        server.start()


if __name__ == '__main__':

    # Start the server
    with DCSControllerServer(loglevel=logging.NOTICE, channel=1) as server:
        server.start()
