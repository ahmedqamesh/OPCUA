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
# import random as rdm
import time
# from datetime import timedelta
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from collections import deque, Counter
from threading import Thread, Event, Lock
import ctypes as ct

# Third party modules
import coloredlogs as cl
import verboselogs
from canlib import canlib, Frame
from canlib.canlib.exceptions import CanGeneralError
from opcua import Server, ua
import analib

# Other files
try:
    from .objectDictionary import objectDictionary
    from . import CANopenConstants as coc
    from .mirrorClasses import MyDCSController
    from .extend_logging import extend_logging, removeAllHandlers
    from .__version__ import __version__
except (ImportError, ModuleNotFoundError):
    from __version__ import __version__
    from objectDictionary import objectDictionary
    import CANopenConstants as coc
    from mirrorClasses import MyDCSController
    from extend_logging import extend_logging, removeAllHandlers


scrdir = os.path.dirname(os.path.abspath(__file__))


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
    logdir : :obj:`str`, optional
        Directory where log files should be saved to
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
                 file_loglevel=logging.INFO, logdir=None, channel=0,
                 bitrate=125000, xmlfile='dcscontrollerdesign.xml',
                 ipAddress='192.168.1.254',
                 nodes=[]):

        self.__isinit = False
        self.ret = None
        self.__cnt = Counter()

        # Initialize logger
        extend_logging()
        verboselogs.install()
        self.logger = logging.getLogger(__name__)
        """:obj:`~logging.Logger`: Main logger for this class"""
        self.logger.setLevel(logging.DEBUG)
        self.opcua_logger = logging.getLogger('opcua')
        self.opcua_logger.setLevel(logging.WARNING)
        if logdir is None:
            logdir = os.path.join(scrdir, 'log')
        ts = os.path.join(logdir,
                          time.strftime('%Y-%m-%d_%H-%M-%S_OPCUA_Server.'))
        self.__fh = RotatingFileHandler(ts + 'log', backupCount=10,
                                        maxBytes=10 * 1024 * 1024)
        fmt = logging.Formatter(logformat)
        fmt.default_msec_format = '%s.%03d'
        self.__fh.setFormatter(fmt)
        cl.install(fmt=logformat, level=console_loglevel, isatty=True,
                   milliseconds=True)
        self.__fh.setLevel(file_loglevel)
        self.logger.addHandler(self.__fh)
        self.__fh_opcua = RotatingFileHandler(ts + 'opcua.log', backupCount=10,
                                              maxBytes=10 * 1024 * 1024)
        self.__fh_opcua.setFormatter(fmt)
        self.__fh_opcua.setLevel(file_loglevel)
        self.opcua_logger.addHandler(self.__fh_opcua)
        self.logger.info(f'Existing logging Handler: {self.logger.handlers}')

        # Initialize default arguments
        if interface is None:
            interface = 'Kvaser'
        elif interface not in ['Kvaser', 'AnaGate']:
            raise ValueError(f'Possible CAN interfaces are "Kvaser" or '
                             f'"AnaGate" and not "{interface}".')
        self.__interface = interface
        if bitrate is None:
            bitrate = 125000
        bitrate = self._parseBitRate(bitrate)

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
            self.__canMsgThread = Thread(target=self.readCanMessages)
        else:
            self.__ch = analib.Channel(ipAddress, channel, baudrate=bitrate)
            self.__cbFunc = analib.wrapper.dll.CBFUNC(self._anagateCbFunc())
            self.__ch.setCallback(self.__cbFunc)
        self.logger.success(str(self))
        self.__busOn = True
        self.__canMsgQueue = deque([], 10)
        self.__pill2kill = Event()
        self.__lock = Lock()
        self.__kvaserLock = Lock()


        # Get DCS Controller OPC UA Object Type
        self.logger.notice('Get OPC UA Object Type of DCS Controller ...')
        self.__dctni = ua.NodeId.from_string(f'ns={self.__idx};i=1003')
        """|OPCUA| Object Type of |DCS| Controller"""
        self.logger.success('... Done!')

        # Scan nodes
        self.__nodeIds = nodes
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

        self.__connectedPSPPs = {}

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
        else:
            self.logger.exception(exception_value)
        self.__ch.setCallback(ct.cast(None, analib.wrapper.dll.CBFUNC))
        self.stop()
        self.__fh.close()
        self.__fh_opcua.close()
        removeAllHandlers(self.logger)
        removeAllHandlers(self.opcua_logger)
        return True

    @property
    def channel(self):
        """Currently used |CAN| channel. The actual class depends on the used
        |CAN| interface."""
        return self.__ch

    @property
    def channelNumber(self):
        """:obj:`int` : Number of the rurrently used |CAN| channel."""
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
    def canMsgQueue(self):
        """:class:`collections.deque` : Queue object holding incoming |CAN|
        messages. This class supports thread-safe adding and removing of
        elements but not thread-safe iterating. Therefore the designated
        :class:`~threading.Lock` object :attr:`lock` should be acquired before
        accessing it.

        The queue is initialized with a maxmimum length of ``1000`` elements
        to avoid memory problems although it is not expected to grow at all.

        This special class is used instead of the :class:`queue.Queue` class
        because it is iterable and fast."""
        return self.__canMsgQueue

    @property
    def ipAddress(self):
        """:obj:`str` : Network address of the AnaGate partner. Only used for
        AnaGate CAN interfaces."""
        if self.__interface == 'Kvaser':
            raise AttributeError('You are using a Kvaser CAN interface!')
        return self.__ch.ipAddress

    @property
    def lock(self):
        """:class:`~threading.Lock` : Lock object for accessing the incoming
        message queue :attr:`canMsgQueue`"""
        return self.__lock

    @property
    def kvaserLock(self):
        """:class:`~threading.Lock` : Lock object which should be acquired for
        performing read or write operations on the Kvaser |CAN| channel. It
        turned out that bad things can happen if that is not done."""
        return self.__kvaserLock

    @property
    def cnt(self):
        """:class:`~collections.Counter` : Counter holding information about
        quality of transmitting and receiving. Its contens are logged when the
        program ends."""
        return self.__cnt

    @property
    def pill2kill(self):
        """:class:`threading.Event` : Stop event for the message collecting
        method :meth:`readCanMessages`"""
        return self.__pill2kill

    @property
    def connectedPSPPs(self):
        """:obj:`dict` of :obj:`list` of :obj:`list` of :obj:`int` : Internal
        attribute holding information about which |PSPP| chips are connected.
        """
        return self.__connectedPSPPs

    def _parseBitRate(self, bitrate):
        if self.__interface == 'Kvaser':
            if bitrate not in coc.CANLIB_BITRATES:
                raise ValueError(f'Bitrate {bitrate} not in list of allowed '
                                 f'values!')
            return coc.CANLIB_BITRATES[bitrate]
        else:
            if bitrate not in analib.constants.BAUDRATES:
                raise ValueError(f'Bitrate {bitrate} not in list of allowed '
                                 f'values!')
            return bitrate

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
                    self.__ch = \
                        canlib.openChannel(self.__channel,
                                           canlib.canOPEN_ACCEPT_VIRTUAL)
                    self.logger.info(str(self))
                    self.__ch.setBusParams(self.__bitrate)
                    if not self.__busOn:
                        self.logger.notice('Going in \'Bus On\' state ...')
                        self.__busOn = True
                    self.__ch.busOn()
                    self.__canMsgThread = Thread(target=self.readCanMessages)
                    self.__canMsgThread.start()
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
                # self.rdmSetConnPSPPs()
                # Do this instead
                for nodeId in self.__nodeIds:
                    self.mypyDCs[nodeId].Status = True
                self.getConnectedPSPPs()
                self.logger.success('Initialization Done.')
                self.run()
            except BusEmptyError as ex:
                self.__isinit = False
                self.logger.error(ex)
                self.stop()
                self.logger.notice('Restarting in 60 seconds ...')
                time.sleep(60)
        else:
            self.logger.critical('The third try failed. Exiting.')

    def stop(self):
        """Close |CAN| channel and stop the |OPCUA| server

        Make sure that this is called so that the connection is closed in a
        correct manner. When this class is used within a :obj:`with` statement
        this method is called automatically when the statement is exited.
        """
        with self.lock:
            self.cnt['Residual CAN messages'] = len(self.__canMsgQueue)
        self.logger.notice(f'Error counters: {self.cnt}')
        self.logger.warning('Stopping helper threads. This might take a '
                            'minute')
        self.__pill2kill.set()
        if self.__busOn:
            if self.__interface == 'Kvaser':
                try:
                    self.__canMsgThread.join()
                except RuntimeError:
                    pass
                self.logger.warning('Going in \'Bus Off\' state.')
                self.__ch.busOff()
            else:
                pass
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
        """Start actual CANopen communication

        This function contains an endless loop in which it is looped over all
        connected |DCS| Controllers and |PSPP| chips. Each value is read using
        :meth:`sdoRead` and written to its corresponding |OPCUA| node if the
        SDO read protocol was succesful.
        """

        count = 0
        while True:
            count = 0 if count == 10 else count
            # Loop over all connected CAN nodeIds
            for nodeId in self.__nodeIds:
                # Loop over all SCB masters
                for scb in range(4):
                    # Reread connected PSPPs in case the user has changed it
                    val = self.mypyDCs[nodeId][scb].ConnectedPSPPs
                    self.__connectedPSPPs[nodeId][scb] = \
                        [i for i in range(16) if int(f'{val:016b}'[::-1][i])]
                    # Loop over all possible PSPPs
                    for pspp in self.__connectedPSPPs[nodeId][scb]:
                        PSPP = self.mypyDCs[nodeId][scb][pspp]
                        index = 0x2200 | (scb << 4) | pspp
                        # Loop over PSPP monitoring data
                        monVals = self.sdoRead(nodeId, index, 1, 3000)
                        if monVals is not None:
                            vals = [(monVals >> i * 10) & (2**10 - 1)
                                    for i in range(3)]
                            for v, name in zip(vals, coc.PSPPMONVALS):
                                PSPP.MonitoringData[name] = v
                                PSPP.MonitoringData.serverWriting[name] = True
                                PSPP.MonitoringData.write(name)
                        # Read less often than monitoring values
                        if True:
                            val = bool(self.sdoRead(nodeId, index, 2, 1000))
                            PSPP.Status = val
                            PSPP.serverWriting['Status'] = True
                            PSPP.write('Status')
                            # Loop over ADC channels
                            for ch in range(8):
                                val = self.sdoRead(nodeId, index, 0x20 | ch,
                                                   1000)
                                if val is not None:
                                    PSPP.ADCChannels[ch] = val
                                    PSPP.ADCChannels.serverWriting[f'Ch{ch}']=\
                                        True
                                    PSPP.ADCChannels.write(f'Ch{ch}')
                            # Loop over registers
                            for name in coc.PSPP_REGISTERS:
                                val = self.sdoRead(nodeId, index, 0x10 |
                                                   coc.PSPP_REGISTERS[name],
                                                   1000)
                                if val is not None:
                                    PSPP.Regs[name] = val
                                    PSPP.Regs.serverWriting[name] = True
                                    PSPP.Regs.write(name)
            count += 1
            # time.sleep(60)

    def readCanMessages(self):
        """Read incoming |CAN| messages and store them in the queue
        :attr:`canMsgQueue`.

        This method runs an endless loop which can only be stopped by setting
        the :class:`~threading.Event` :attr:`pill2kill` and is therefore
        designed to be used as a :class:`~threading.Thread`.
        """
        self.logger.notice('Starting pulling of CAN messages')
        while not self.__pill2kill.is_set():
            try:
                if self.__interface == 'Kvaser':
                    with self.__kvaserLock:
                        frame = self.__ch.read()
                    cobid, data, dlc, flag, t = (frame.id, frame.data,
                                                 frame.dlc, frame.flags,
                                                 frame.timestamp)
                    if frame is None or (cobid == 0 and dlc == 0):
                        raise canlib.CanNoMsg
                else:
                    cobid, data, dlc, flag, t = self.__ch.getMessage()
                with self.__lock:
                    self.__canMsgQueue.appendleft((cobid, data, dlc, flag, t))
                self.dumpMessage(cobid, data, dlc, flag)
            except (canlib.CanNoMsg, analib.CanNoMsg):
                pass

    def _anagateCbFunc(self):
        """Wraps the callback function for AnaGate |CAN| interfaces. This is
        neccessary in order to have access to the instance attributes.

        The callback function is called asychronous but the instance attributes
        are accessed in a thread-safe way.

        Returns
        -------
        cbFunc
            Function pointer to the callback function
        """

        def cbFunc(cobid, data, dlc, flag, handle):
            """Callback function.

            Appends incoming messages to the message queue and logs them.

            Parameters
            ----------
            cobid : :obj:`int`
                |CAN| identifier
            data : :class:`~ctypes.c_char` :func:`~cytpes.POINTER`
                |CAN| data - max length 8. Is converted to :obj:`bytes` for
                internal treatment using :func:`~ctypes.string_at` function. It
                is not possible to just use :class:`~ctypes.c_char_p` instead
                because bytes containing zero would be interpreted as end of
                data.
            dlc : :obj:`int`
                Data Length Code
            flag : :obj:`int`
                Message flags
            handle : :obj:`int`
                Internal handle of the AnaGate channel. Just needed for the API
                class to work.
            """
            data = ct.string_at(data, dlc)
            t = time.time()
            with self.__lock:
                self.__canMsgQueue.appendleft((cobid, data, dlc, flag, t))
            self.dumpMessage(cobid, data, dlc, flag)

        return cbFunc

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

    def writeMessage(self, cobid, msg, flag=0, timeout=None):
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
            |SDO| write timeout in milliseconds. When :data:`None` or not
            given an infinit timeout is used.
        """
        if self.__interface == 'Kvaser':
            if timeout is None:
                timeout = 0xFFFFFFFF
            with self.__kvaserLock:
                self.__ch.writeWait(Frame(cobid, msg), timeout)
        else:
            self.__ch.write(cobid, msg, flag)

    def sdoRead(self, nodeId, index, subindex, timeout=100):
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
        self.cnt['SDO read total'] += 1
        self.logger.info(f'Send SDO read request to node {nodeId}.')
        cobid = coc.COBID.SDO_RX + nodeId
        msg = [0 for i in range(coc.MAX_DATABYTES)]
        msg[1], msg[2] = index.to_bytes(2, 'little')
        msg[3] = subindex
        msg[0] = 0x40
        try:
            self.writeMessage(cobid, msg, timeout=timeout)
        except CanGeneralError:
            self.cnt['SDO read request timeout'] += 1
            return None
        # Wait for response
        t0 = time.perf_counter()
        messageValid = False
        while time.perf_counter() - t0 < timeout / 1000:
            with self.__lock:
                for i, (cobid_ret, ret, dlc, flag, t) in \
                        zip(range(len(self.__canMsgQueue)),
                            self.__canMsgQueue):
                    messageValid = \
                        (cobid_ret == coc.COBID.SDO_TX + nodeId and
                         ret[0] in [0x80, 0x43, 0x47, 0x4b, 0x4f] and
                         int.from_bytes([ret[1], ret[2]], 'little') == index
                         and ret[3] == subindex and
                         dlc == 8)
                    if messageValid:
                        del self.__canMsgQueue[i]
                        break
            if messageValid:
                break
        else:
            self.logger.info(f'SDO read response timeout (node {nodeId}, index'
                             f' {index:04X}:{subindex:02X})')
            self.cnt['SDO read response timeout'] += 1
            return None
        # Check command byte
        if ret[0] == 0x80:
            self.logger.error('Received SDO abort message')
            self.cnt['SDO read abort'] += 1
            return None
        nDatabytes = 4 - ((ret[0] >> 2) & 0b11)
        data = []
        for i in range(nDatabytes):
            data.append(ret[4 + i])
        self.logger.info(f'Got data: {data}')
        return int.from_bytes(data, 'little')

    def sdoWrite(self, nodeId, index, subindex, value, timeout=3000):
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
        self.logger.notice(f'Send SDO write request to node {nodeId}.')
        self.logger.notice(f'Writing value {value:X}')
        self.cnt['SDO write total'] += 1
        cobid = coc.COBID.SDO_RX + nodeId
        datasize = len(f'{value:X}') // 2 + 1
        data = value.to_bytes(4, 'little')
        msg = [0 for i in range(8)]
        msg[0] = (((0b00010 << 2) | (4 - datasize)) << 2) | 0b11
        msg[1], msg[2] = index.to_bytes(2, 'little')
        msg[3] = subindex
        msg[4:] = [data[i] for i in range(4)]
        # Send the request message
        try:
            self.writeMessage(cobid, msg)
        except CanGeneralError:
            self.cnt['SDO write request timeout'] += 1
            return False
        except analib.exception.DllException as ex:
            self.logger.exception(ex)
            self.cnt['SDO write request timeout'] += 1
            return False

        # Read the response from the bus
        t0 = time.perf_counter()
        messageValid = False
        while time.perf_counter() - t0 < timeout / 1000:
            with self.lock:
                for i, (cobid_ret, ret, dlc, flag, t) in \
                        zip(range(len(self.__canMsgQueue)),
                            self.__canMsgQueue):
                    messageValid = \
                        (cobid_ret == coc.COBID.SDO_TX + nodeId and
                         ret[0] in [0x80, 0b1100000] and
                         int.from_bytes([ret[1], ret[2]], 'little') == index
                         and ret[3] == subindex and
                         dlc == 8)
                    if messageValid:
                        del self.__canMsgQueue[i]
                        break
            if messageValid:
                break
        else:
            self.logger.warning('SDO write timeout')
            self.cnt['SDO write timeout'] += 1
            return False
        # Analyse the response
        if ret[0] == 0x80:
            abort_code = int.from_bytes(ret[4:], 'little')
            self.logger.error('Got SDO abort message. Abort code: '
                              f'{abort_code:08X}')
            self.cnt['SDO write abort'] += 1
            return False
        else:
            self.logger.success('SDO write protocol successful!')
        return True

    def getConnectedPSPPs(self):
        """Read the `ConnectedPSPPs` |OD| attribute from the connected |DCS|
        Controllers. The received values are stored in the attribute
        :attr:`connectedPSPPs` and written to their corresponding |OPCUA| node.
        """
        attr = 'ConnectedPSPPs'
        for nodeId in self.__nodeIds:
            self.__connectedPSPPs[nodeId] = [[] for scb in range(4)]
            for scb in range(4):
                val = None
                while val is None:
                    val = self.sdoRead(nodeId, 0x2000, 1 + scb, 3000)
                self.mypyDCs[nodeId][scb].ConnectedPSPPs = val
                self.mypyDCs[nodeId][scb].serverWriting[attr] = True
                self.mypyDCs[nodeId][scb].write(attr)
                self.__connectedPSPPs[nodeId][scb] = \
                    [i for i in range(16) if int(f'{val:016b}'[::-1][i])]
                self.logger.debug(f'Connected PSPPs: {val}')

    def scanNodes(self, timeout=100):
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
                            'sebastian.scholz@cern.ch',
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.set_defaults(interface='Kvaser')

    # Server configuration group
    sGroup = parser.add_argument_group('OPC UA server configuration')
    sGroup.add_argument('-E', '--endpoint', metavar='ENDPOINT',
                        help='Endpoint of the OPCUA server',
                        default='opc.tcp://localhost:4840/')
    sGroup.add_argument('-e', '--edsfile', metavar='EDSFILE',
                        default=os.path.join(scrdir,
                                             'CANControllerForPSPPv1.eds'),
                        help='File path of Electronic Data Sheet (EDS)')
    sGroup.add_argument('-x', '--xmlfile', metavar='XMLFILE',
                        default=os.path.join(scrdir,
                                             'dcscontrollerdesign.xml'),
                        help='File path of OPCUA XML design file')

    # CAN interface
    CGroup = parser.add_argument_group('CAN interface')
    iGroup = CGroup.add_mutually_exclusive_group()
    iGroup.add_argument('-K', '--kvaser', action='store_const', const='Kvaser',
                        dest='interface',
                        help='Use Kvaser CAN interface (default). When no '
                        'Kvaser interface is found or connected a virtual '
                        'channel is used.')
    iGroup.add_argument('-A', '--anagate', action='store_const',
                        const='AnaGate', dest='interface',
                        help='Use AnaGate Ethernet CAN interface')

    # CAN settings group
    cGroup = parser.add_argument_group('CAN settings')
    cGroup.add_argument('-C', '--channel', metavar='CHANNEL', type=int,
                        help='Number of CAN channel to use', default=0)
    cGroup.add_argument('-i', '--ipaddress', metavar='IPADDRESS',
                        default='192.168.1.254', dest='ipAddress',
                        help='IP address of the AnaGate Ethernet CAN '
                        'interface')
    cGroup.add_argument('-b', '--bitrate', metavar='BITRATE', type=int,
                        default=125000,
                        help='CAN bitrate as integer in bit/s')

    # Logging configuration
    lGroup = parser.add_argument_group('Logging settings')
    lGroup.add_argument('-c', '--console_loglevel',
                        choices={'NOTSET', 'SPAM', 'DEBUG', 'VERBOSE', 'INFO',
                                 'NOTICE', 'SUCCESS', 'WARNING', 'ERROR',
                                 'CRITICAL'},
                        default='NOTICE',
                        help='Level of console logging')
    lGroup.add_argument('-f', '--file_loglevel',
                        choices={'NOTSET', 'SPAM', 'DEBUG', 'VERBOSE', 'INFO',
                                 'NOTICE', 'SUCCESS', 'WARNING', 'ERROR',
                                 'CRITICAL'},
                        default='INFO',
                        help='Level of file logging')
    lGroup.add_argument('-d', '--logdir', metavar='LOGDIR',
                        default=os.path.join(scrdir, 'log'),
                        help='Directory where log files should be stored')

    # Program version
    parser.add_argument('-v', '--version', action='version',
                        version=__version__)
    args = parser.parse_args()

    # Start the server
    with DCSControllerServer(**vars(args)) as server:
        server.start()


if __name__ == '__main__':

    main()
