# -*- coding: utf-8 -*-
"""
Main wrapper of AnaGate |API|

The wrapped |API| functions are adapted in such a manner that they can be used
in a pythonic way including class structure. The user only sees and gives
Python build-in data types from and to the functions.

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal
"""

# Standard library modules
import ctypes as ct
import logging
import time
import ipaddress
import threading

# Other files in this package
from .wrapper import dll, restart
from .exception import DllException, CanNoMsg
from .constants import CONNECT_STATES, BAUDRATES


@dll.CBFUNC
def cbFunc(cobid, data, dlc, flags, handle):
    """Example callback function for incoming |CAN| messages.

    The arguments are passed as python build-in data types.
    """
    data = ct.string_at(data, dlc)
    print('Calling callback function with the following arguments:')
    print(f'    COBID: {cobid:03X}; Data: {data[:dlc].hex()}; DLC: {dlc}; '
          f'Flags: {flags}; Handle: {handle}')


class Channel(object):
    """Open a connection to an Anagate |CAN| channel.

    Parameters
    ----------
    ipAddress : :obj:`str`, optional
        Network address of the AnaGate partner. Defaults to ``'192.168.1.254'``
        which is the factory default.
    port : :obj:`int`, optional
        |CAN| port number.
        Allowed values are:

        * 0 for port 1/A (all AnaGate |CAN| models)
        * 1 for port 2/B (AnaGate |CAN| duo, AnaGate |CAN| quattro,
          AnaGate CAN X2/X4/X8)
        * 2 for port 3/C (AnaGate |CAN| quattro, AnaGate |CAN| X4/X8)
        * 3 for port 4/D (AnaGate |CAN| quattro, AnaGate |CAN| X4/X8)
        * 4 for port 5/E (AnaGate |CAN| X8)
        * 5 for port 6/F (AnaGate |CAN| X8)
        * 6 for port 7/G (AnaGate |CAN| X8)
        * 7 for port 8/H (AnaGate |CAN| X8)

        Defaults to 0.
    confirm : :obj:`bool`, optional
        If set to :data:`True`, all incoming and outgoing data requests are
        confirmed by the internal message protocol. Without confirmations a
        better transmission performance is reached. Defaults to :data:`True`.
    ind : :obj:`bool`, optional
        If set to :data:`False`, all incoming telegrams are discarded.
        Defaults to :data:`True`.
    timeout : :obj:`int`, optional
        Default timeout for accessing the AnaGate in milliseconds.

        A timeout is reported if the AnaGate partner does not respond within
        the defined timeout period. This global timeout value is valid on the
        current network connection for all commands and functions which do not
        offer a specific timeout value.

        Defaults to 10 s.
    baudrate : :obj:`int`, optional
        The baud rate to be used.
        The following values are supported:

        * 10000 für 10kBit
        * 20000 für 20kBit
        * 50000 für 50kBit
        * 62500 für 62.5kBit
        * 100000 für 100kBit
        * 125000 für 125kBit
        * 250000 für 250kBit
        * 500000 für 500kBit
        * 800000 für 800kBit (not AnaGate CAN)
        * 1000000 für 1MBit

    operatingMode : :obj:`int`, optional
        The operating mode to be used.
        The following values are allowed:

        * 0 = default mode.
        * 1 = loop back mode: No telegrams are sent via |CAN| bus. Instead they
          are received as if they had been transmitted over |CAN| by a
          different |CAN| device.
        * 2 = listen mode: Device operates as a passive bus partner, meaning no
          telegrams are sent to the |CAN| bus (nor ACKs for incoming
          telegrams).
        * 3 = offline mode: No telegrams are sent or received on the |CAN| bus.
          Thus no error frames are generated on the bus if other connected
          |CAN| devices send telegrams with a different baud rate.

    termination : :obj:`bool`, optional
        Use integrated |CAN| bus termination. This setting is not supported by
        all AnaGate |CAN| models.
    highSpeedMode : :obj:`bool`, optional
        Use high speed mode. This setting is not supported by all AnaGate |CAN|
        models.

        The high speed mode was created for large baud rates with continuously
        high bus load. In this mode telegrams are not confirmed on the protocol
        layer and the software filters defined via CANSetFilter are ignored.
    timeStampOn : :obj:`bool`, optional
        Use time stamp mode. This setting is not supported by all AnaGate |CAN|
        models.

        In activated time stamp mode an additional timestamp is sent with the
        CAN telegram. This timestamp indicates when the incoming message was
        received by the |CAN| controller or when the outgoing message was
        confirmed by the |CAN| controller.
    maxSizePerQueue : :obj:`int`, optional
        Maximum size of the receive buffer. Defaults to 1000.
    """


    def __init__(self, ipAddress='192.168.1.254', port=0, confirm=True,
                 ind=True, timeout=10000, baudrate=125000, operatingMode=0,
                 termination=True, highSpeedMode=False, timeStampOn=False,
                 maxSizePerQueue=1000):

        # Value checks
        if baudrate not in BAUDRATES:
            raise ValueError(f'Baudrate value {baudrate} is not allowed!')
        if operatingMode not in range(4):
            raise ValueError(f'Operating mode must be 0, 1, 2 or 3, but is '
                             f'{operatingMode}')
        # Raises ValueError if ipAddress is invalid
        ipaddress.ip_address(ipAddress)

        # Initialize Lock
        self.__lock = threading.Lock()

        # Initialize private attributes containing ctypes variables
        self.__deviceOpen = False
        self.__handle = ct.c_int32()
        self.__port = ct.c_int32()
        self.__sendDataConfirm = ct.c_int32()
        self.__sendDataInd = ct.c_int32()
        self.__ipAddress = ct.create_string_buffer(bytes(ipAddress, 'utf-8'))
        self.__baudrate = ct.c_uint32(baudrate)
        self.__operatingMode = ct.c_uint8(operatingMode)
        self.__termination = ct.c_int32(int(termination))
        self.__highSpeedMode = ct.c_int32(int(highSpeedMode))
        self.__timeStampOn = ct.c_int32(int(timeStampOn))
        self.__maxSizePerQueue = ct.c_uint32(maxSizePerQueue)

        # Establish connection with Anagate partner and set configuration
        self._openDevice(ipAddress, port, confirm, ind, timeout)
        self.setGlobals()
        self.setTime()
        self._setMaxSizePerQueue(maxSizePerQueue)
        # self.setCallback(cbFunc)

    def __str__(self):
        return (f'Anagate CAN channel: IP address: {self.ipAddress}; '
                f'CAN port: {self.port}')

    __repr__ = __str__

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.close()
        logging.exception(exception_value)
        return True

    def __del__(self):
        self.close()

    @property
    def lock(self):
        """:class:`threading.Lock` : Lock object for accessing the channel"""
        return self.__lock

    @property
    def handle(self):
        """:obj:`int` : Access handle"""
        return self.__handle.value

    @property
    def port(self):
        """:obj:`int` : |CAN| port number"""
        return self.__port.value

    @property
    def sendDataConfirm(self):
        """:obj:`bool` : If :data:`True`, all incoming and outgoing data
        requests are confirmed by the internal message protocol. Without
        confirmations a better transmission performance is reached.
        """
        return bool(self.__sendDataConfirm.value)

    @property
    def sendDataInd(self):
        """:obj:`bool` : If set to :data:`False`, all incoming telegrams are
        discarded."""
        return bool(self.__sendDataInd.value)

    @property
    def ipAddress(self):
        """:obj:`str` : Network address of the AnaGate partner."""
        return self.__ipAddress.value.decode()

    @property
    def baudrate(self):
        """:obj:`int` : The baud rate to be used.

        The following values are supported:

        * 10000 für 10kBit
        * 20000 für 20kBit
        * 50000 für 50kBit
        * 62500 für 62.5kBit
        * 100000 für 100kBit
        * 125000 für 125kBit
        * 250000 für 250kBit
        * 500000 für 500kBit
        * 800000 für 800kBit (not AnaGate CAN)
        * 1000000 für 1MBit

        """
        self.getGlobals()
        return self.__baudrate.value

    @baudrate.setter
    def baudrate(self, value):
        assert type(value) is int
        if value not in BAUDRATES:
            raise ValueError(f'Baudrate value {value} is not allowed!')
        self.__baudrate.value = value
        self.setGlobals()

    @property
    def operatingMode(self):
        """:obj:`int` : The operating mode to be used.

        The following values are allowed:

        * 0 = default mode.
        * 1 = loop back mode: No telegrams are sent via |CAN| bus. Instead they
          are received as if they had been transmitted over |CAN| by a
          different |CAN| device.
        * 2 = listen mode: Device operates as a passive bus partner, meaning no
          telegrams are sent to the |CAN| bus (nor ACKs for incoming
          telegrams).
        * 3 = offline mode: No telegrams are sent or received on the |CAN| bus.
          Thus no error frames are generated on the bus if other connected
          |CAN| devices send telegrams with a different baud rate.

        """
        self.getGlobals()
        return self.__operatingMode.value

    @operatingMode.setter
    def operatingMode(self, value):
        assert type(value) is int
        if value not in range(4):
            raise ValueError(f'Operating mode must be 0, 1, 2 or 3, but is '
                             f'{value}')
        self.__operatingMode.value = value
        self.setGlobals()

    @property
    def termination(self):
        """:obj:`bool` : Use high speed mode.

        This setting is not supported by all AnaGate |CAN| models.
        """
        self.getGlobals()
        return bool(self.__termination.value)

    @termination.setter
    def termination(self, value):
        assert type(value) is bool
        self.__termination.value = int(value)
        self.setGlobals()

    @property
    def highSpeedMode(self):
        """:obj:`bool` : Use high speed mode.

        This setting is not supported by all AnaGate |CAN| models.

        The high speed mode was created for large baud rates with continuously
        high bus load. In this mode telegrams are not confirmed on the protocol
        layer and the software filters defined via CANSetFilter_ are ignored.
        """
        self.getGlobals()
        return bool(self.__highSpeedMode.value)

    @highSpeedMode.setter
    def highSpeedMode(self, value):
        assert type(value) is int
        self.__highSpeedMode.value = int(value)
        self.setGlobals()

    @property
    def timeStampOn(self):
        """:obj:`bool` : Use time stamp mode.

        This setting is not supported by all AnaGate |CAN| models.

        In activated time stamp mode an additional timestamp is sent with the
        CAN telegram. This timestamp indicates when the incoming message was
        received by the |CAN| controller or when the outgoing message was
        confirmed by the |CAN| controller.
        """
        self.getGlobals()
        return bool(self.__timeStampOn.value)

    @timeStampOn.setter
    def timeStampOn(self, value):
        assert type(value) is bool
        self.__timeStampOn.value = int(value)
        self.setGlobals()

    @property
    def state(self):
        """:obj:`str` : Parses the integer connection state to a meaningful
        string.

        Possible values are:

        * ``'DISCONNECTED'``
        * ``'CONNECTING'``
        * ``'CONNECTED'``
        * ``'DISCONNECTING'``
        * ``'NOT_INITIALIZED'``

        """
        if self.__deviceOpen:
            return CONNECT_STATES[self._deviceConnectState()]
        return 'DISCONNECTED'

    @property
    def maxSizePerQueue(self):
        """:obj:`int` : Maximum size of the receive buffer."""
        return self.__maxSizePerQueue.value

    @maxSizePerQueue.setter
    def maxSizePerQueue(self, value):
        assert type(value) is int
        if value < 0:
            raise ValueError(f'Value {value} of maxSizePerQueue is < 0.')
        self._setMaxSizePerQueue(value)
        self.__maxSizePerQueue.value = value

    @property
    def deviceOpen(self):
        """:obj:`bool` : If the Access handle is valid"""
        return self.__deviceOpen

    def _openDevice(self, ipAddress='192.168.1.254', port=0, confirm=True,
                    ind=True, timeout=10000):
        """Opens an network connection (|TCP| or |UDP|) to an AnaGate |CAN|
        device.

        Opens a |TCPIP| connection to an |CAN| interface of an AnaGate |CAN|
        device. If the connection is established, |CAN| telegrams can be sent
        and received.

        The connection should be closed with the function :func:`_closeDevice`
        if not longer needed.

        Parameters
        ----------
        ipAddress : :obj:`str`, optional
            Network address of the AnaGate partner. Defaults to '192.168.1.254'
            which is the factory default.
        port : :obj:`int`, optional
            |CAN| port number.
            Allowed values are:

            * 0 for port 1/A (all AnaGate |CAN| models)
            * 1 for port 2/B (AnaGate |CAN| duo, AnaGate |CAN| quattro,
              AnaGate |CAN| X2/X4/X8)
            * 2 for port 3/C (AnaGate |CAN| quattro, AnaGate |CAN| X4/X8)
            * 3 for port 4/D (AnaGate |CAN| quattro, AnaGate |CAN| X4/X8)
            * 4 for port 5/E (AnaGate |CAN| X8)
            * 5 for port 6/F (AnaGate |CAN| X8)
            * 6 for port 7/G (AnaGate |CAN| X8)
            * 7 for port 8/H (AnaGate |CAN| X8)

            Defaults to 0.
        confirm : :obj:`bool`, optional
            If set to :data:`True`, all incoming and outgoing data requests
            are confirmed by the internal message protocol. Without
            confirmations a better transmission performance is reached.
            Defaults to :data:`True`.
        ind : :obj:`bool`, optional
            If set to :data:`False`, all incoming telegrams are discarded.
            Defaults to :data:`True`.
        timeout : :obj:`int`, optional
            Default timeout for accessing the AnaGate in milliseconds.

            A timeout is reported if the AnaGate partner does not respond
            within the defined timeout period. This global timeout value is
            valid on the current network connection for all commands and
            functions which do not offer a specific timeout value.

            Defaults to 10 s.
       """

        bSendDataConfirm = ct.c_int32(int(confirm))
        bSendDataInd = ct.c_int32(int(ind))
        nCANPort = ct.c_int32(port)
        pcIPAddress = ct.create_string_buffer(bytes(ipAddress, 'utf-8'))
        nTimeout = ct.c_int32(timeout)

        with self.__lock:
            dll.CANOpenDevice(ct.byref(self.__handle), bSendDataConfirm,
                              bSendDataInd, nCANPort, pcIPAddress, nTimeout)

        self.__port = nCANPort
        self.__sendDataConfirm = bSendDataConfirm
        self.__sendDataInd = bSendDataInd
        self.__ipAddress = pcIPAddress
        self.__deviceOpen = True
        return True

    def _closeDevice(self):
        """Closes an open network connection to an AnaGate |CAN| device."""
        with self.__lock:
            dll.CANCloseDevice(self.__handle)
        self.__deviceOpen = False

    def close(self):
        """Close a connection.

        If the wrapped function returns an error the connection was already
        closed and the error is ignored.
        """
        try:
            self._closeDevice()
        except DllException:
            pass

    def openChannel(self):
        """Opens a connection if it is not already open"""
        if not self.__deviceOpen:
            return self._openDevice(self.ipAddress, self.port,
                                    self.sendDataConfirm, self.sendDataInd)

    def restart(self):
        """Restart the AnaGate device"""
        with self.__lock:
            restart(self.ipAddress)

    def setGlobals(self, baudrate=None, operatingMode=None, termination=None,
                   highSpeedMode=None, timeStampOn=None):
        """Sets the global settings which are to be used on the |CAN| bus.

        Sets the global settings of the used |CAN| interface. These settings
        are effective for all concurrent connections to the |CAN| interface.
        The settings are not saved permanently on the device and are reset
        after every device restart.

        Parameters
        ----------
        baudrate : :obj:`int`, optional
            The baud rate to be used.
            The following values are supported:

            * 10000 für 10kBit
            * 20000 für 20kBit
            * 50000 für 50kBit
            * 62500 für 62.5kBit
            * 100000 für 100kBit
            * 125000 für 125kBit
            * 250000 für 250kBit
            * 500000 für 500kBit
            * 800000 für 800kBit (not AnaGate |CAN|)
            * 1000000 für 1MBit

        operatingMode : :obj:`int`, optional
            The operating mode to be used.
            The following values are allowed:

            * 0 = default mode.
            * 1 = loop back mode: No telegrams are sent via |CAN| bus. Instead
              they are received as if they had been transmitted over |CAN| by a
              different |CAN| device.
            * 2 = listen mode: Device operates as a passive bus partner,
              meaning no telegrams are sent to the |CAN| bus (nor ACKs for
              incoming telegrams).
            * 3 = offline mode: No telegrams are sent or received on the |CAN|
              bus. Thus no error frames are generated on the bus if other
              connected CAN devices send telegrams with a different baud rate.

        termination : :obj:`bool`, optional
            Use integrated |CAN| bus termination. This setting is not supported
            by all AnaGate CAN models.
        highSpeedMode : :obj:`bool`, optional
            Use high speed mode. This setting is not supported by all AnaGate
            CAN models.

            The high speed mode was created for large baud rates with
            continuously high bus load. In this mode telegrams are not
            confirmed on the protocol layer and the software filters defined
            via CANSetFilter_ are ignored.
        timeStampOn : :obj:`bool`, optional
            Use time stamp mode. This setting is not supported by all AnaGate
            CAN models.

            In activated time stamp mode an additional timestamp is sent with
            the |CAN| telegram. This timestamp indicates when the incoming
            message was received by the |CAN| controller or when the outgoing
            message was confirmed by the |CAN| controller.
       """
        baudrate = self.__baudrate if baudrate is None \
            else ct.c_uint32(baudrate)
        operatingMode = self.__operatingMode if operatingMode is None \
            else ct.c_uint8(operatingMode)
        termination = self.__termination if termination is None \
            else ct.c_int32(int(termination))
        highSpeedMode = self.__highSpeedMode if highSpeedMode is None \
            else ct.c_int32(int(highSpeedMode))
        timeStampOn = self.__timeStampOn if timeStampOn is None \
            else ct.c_int32(timeStampOn)

        with self.__lock:
            dll.CANSetGlobals(self.__handle, baudrate, operatingMode,
                              termination, highSpeedMode, timeStampOn)
        self.__baudrate = baudrate
        self.__operatingMode = operatingMode
        self.__termination = termination
        self.__highSpeedMode = highSpeedMode
        self.__timeStampOn = timeStampOn

    def getGlobals(self):
        """Gets the currently used global settings on the |CAN| bus.

        Returns the global settings of the used |CAN| interface. These settings
        are effective for all concurrent connections to the |CAN| interface.

        Saves the received values in the corresponding private attributes.
        """
        with self.__lock:
            dll.CANGetGlobals(self.__handle, ct.byref(self.__baudrate),
                              ct.byref(self.__operatingMode),
                              ct.byref(self.__termination),
                              ct.byref(self.__highSpeedMode),
                              ct.byref(self.__timeStampOn))

    def setTime(self, seconds=None, microseconds=0):
        """Sets the current system time on the AnaGate device.

        The CANSetTime_ function sets the system time on the AnaGate hardware.
        If the time stamp mode is switched on by the :func:`setGlobals`
        function, the AnaGate hardware adds a time stamp to each incoming |CAN|
        telegram and a time stamp to the confirmation of a telegram sent via
        the |API| (only if confirmations are switched on for data requests).

        Parameters
        ----------
        seconds : :obj:`float`
            Time in seconds from 01.01.1970. Defaults to :data:`None`. In that
            case the current system time is used.
        microseconds : :obj:`int`, optional
            Micro seconds. Defaults to 0.
        """
        if seconds is None:
            seconds = time.time()
            microseconds = int((seconds - int(seconds)) * 1000000)
            seconds = int(seconds)
        seconds = ct.c_uint32(seconds)
        microseconds = ct.c_uint32(microseconds)

        with self.__lock:
            dll.CANSetTime(self.__handle, seconds, microseconds)

    def getTime(self):
        """Gets the current system time from the AnaGate CAN device.

        If the time stamp mode is switched on by the CANSetGlobals_
        function, the AnaGate hardware adds a time stamp to each incoming |CAN|
        telegram and a time stamp to the confirmation of a telegram sent via
        the |API| (only if confirmations are switched on for data requests).

        Returns
        -------
        seconds : :obj:`int`
            Time in seconds from 01.01.1970.
        microseconds : :obj:`int`
            Additional microseconds.
        """
        seconds = ct.c_uint32()
        microseconds = ct.c_uint32()
        timeWasSet = ct.c_int32()

        with self.__lock:
            dll.CANGetTime(self.__handle, ct.byref(timeWasSet),
                           ct.byref(seconds), ct.byref(microseconds))
        return seconds.value, microseconds.value

    def write(self, identifier, data, flags=0):
        """Sends a |CAN| telegram to the |CAN| bus via the AnaGate device.

        Parameters
        ----------
        identifier : :obj:`int`
            |CAN| identifier of the sender. Parameter flags defines whether the
            address is in extended format (29-bit) or standard format (11-bit).
        data : :obj:`list` of :obj:`int`
            Data content given as a list of integers. Data length is computed
            from this list.
        flags : :obj:`int`, optional
            The format flags are defined as follows:

            * Bit 0: If set, the |CAN| identifier is in extended format (29
              bit), otherwise not (11 bit).
            * Bit 1: If set, the telegram is marked as remote frame.
            * Bit 2: If set, the telegram has a valid timestamp. This bit is
              only set for incoming data telegrams and doesn't need to be set
              for the CANWrite_ and CANWriteEx_ functions.
        """
        buffer = ct.create_string_buffer(bytes(data))
        bufferLen = ct.c_int32(len(data))
        flags = ct.c_int32(flags)
        identifier = ct.c_int32(identifier)

        with self.__lock:
            dll.CANWrite(self.__handle, identifier, buffer, bufferLen, flags)

    def _setMaxSizePerQueue(self, maxSize):
        """Sets the maximum size of the queue that buffers received |CAN|
        telegrams.

        Sets the maximum size of the queue that buffers received |CAN|
        telegrams. No telegrams are buffered before this function is called.
        Once received telegrams have been added to the buffer they can be read
        with :func:`getMessage`. If the queue is full while a new telegram is
        received then it gets discarded.

        If the queue size is set to 0 then all previously queued telegrams are
        deleted. However, if the queue size is reduced to a value different
        from 0 then excess telegrams are not discarded. Instead newly received
        telegrams don't get queued until the queue has been freed enough via
        :func:`getMessage` calls, or until the queue size has been increased
        again.

        Note
        ----
        Received telegrams are only buffered if no callback function was
        registered via :func:`setCallback`. Once a callback function has been
        enabled, previously buffered telegrams can still be read via
        :func:`getMessage`. Newly received telegrams are not added to the queue
        though.

        Parameters
        ----------
        maxSize : :obj:`int`
            Maximum size of the receive buffer.
        """
        maxSize = ct.c_uint32(maxSize)

        with self.__lock:
            dll.CANSetMaxSizePerQueue(self.__handle, maxSize)

    def getMessage(self):
        """Returns a received |CAN| telegram from the receive queue.

        Returns a received |CAN| telegram from the receive queue. The caller
        needs to supply memory buffers for the telegram parameters he is
        interested in. Parameters for unneeded values can be NULL pointers.

        The function returns the number of telegrams that are still in the
        queue after the function call via the pnAvailMsgs parameter. This
        variable is set to -1 if no telegram was available in the queue. In
        that case all telegram parameters are invalid.

        Returns
        -------
        cobid : :obj:`int`
            11 bit |CAN| identifier of the telegram
        data : :obj:`bytes`
            Data bytes of the telegram
        dlc : :obj:`int`
            Number of data bytes in the telegram
        flags : :obj:`int`
            Flags of the telegram
        timestamp : :obj:`float`
            Timestamp in seconds since 1.1.1970

        Raises
        ------
        :exc:`~.exception.CanNoMsg`
            If there no available |CAN| messages in the buffer
        """
        availMsgs = ct.c_uint32()
        identifier = ct.c_int32()
        data = ct.create_string_buffer(8)
        dataLen = ct.c_uint8()
        flags = ct.c_int32()
        seconds = ct.c_int32()
        microseconds = ct.c_int32()

        with self.__lock:
            dll.CANGetMessage(self.__handle, ct.byref(availMsgs),
                              ct.byref(identifier), data, ct.byref(dataLen),
                              ct.byref(flags), ct.byref(seconds),
                              ct.byref(microseconds))

        if availMsgs.value == ct.c_uint32(-1).value:
            raise CanNoMsg
        return identifier.value, data.raw[:dataLen.value], dataLen.value, \
            flags.value, seconds.value + microseconds.value / 1000000

    def _deviceConnectState(self):
        """Retrieves the current network connection state of the current
        AnaGate connection.

        This function can be used to check if an already connected device is
        disconnected.

        The detection period of a state change depends on the use of the
        internal AnaGateALIVE mechanism. This ALIVE mechanism has to be
        switched on explicitly via the :func:`startAlive` function. Once
        activated the connection state is periodically checked by the ALIVE
        mechanism.

        Returns
        -------
        state : :obj:`int`
            The current network connection state. The following values are
            possible:

            * 1 = DISCONNECTED: The connection to the AnaGate is
              disconnected.
            * 2 = CONNECTING: The connection is connecting.
            * 3 = CONNECTED : The connection is established.
            * 4 = DISCONNECTING: The connection is disonnecting.
            * 5 = NOT_INITIALIZED: The network protocol is not
              successfully initialized.

        """
        with self.__lock:
            return dll.CANDeviceConnectState(self.__handle)

    def startAlive(self, aliveTime=1):
        """Starts the ALIVE mechanism, which checks periodically the state of
        the network connection to the AnaGate hardware.

        The AnaGate communication protocol (see [TCP-2010]_) supports an
        application specific connection control which allows faster detection
        of broken connection lines.

        The CANStartAlive_ function starts a concurrent thread in the |DLL| in
        order to send defined alive telegrams (ALIVE_REQ) peridically (approx.
        every half of the given time out) to the Anagate device via the current
        network connection. If the alive telegram is not confirmed within the
        alive time the connection is marked as disconnected and the socket is
        closed if not already closed.

        Use the :func:`_deviceConnectState` function to check the current
        network connection state.

        Parameters
        ----------
        aliveTime : :obj:`int`, optional
            Time out interval in seconds for the ALIVE mechanism. Defaults to
            1 s.
        """

        with self.__lock:
            dll.CANStartAlive(self.__handle, ct.c_int32(aliveTime))

    def setCallback(self, callbackFunction):
        """Defines an asynchronous callback function which is called for each
        incoming |CAN| telegram.

        Incoming |CAN| telegrams can bei received via a callback function which
        can be set by a simple |API| call. If a callback function is set it
        will be called by the |API| asynchronously.

        Parameters
        ----------
        callbackFunction
            Function pointer to the private callback function. Set this
            parameter to NULL to deactivate the callback function. The
            parameters of the callback function are described in the
            documentation of the CANWrite_ function.
        """
        with self.__lock:
            dll.CANSetCallback(self.__handle, callbackFunction)
