#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
This module provides classes that are used to mirror an |OPCUA| address space.

The main 'magic' (parsing between |OPCUA| nodes, the mirrored objects and the
CANopen_ communication) happens inside descriptors. There are two descriptor
classes which only differ in details because there is one for an unsigned
integer (which is the predominant data type) and one for a boolean.

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
"""

# Standard library modules
from time import sleep

# Third party modules
from opcua import ua, Server

# Other files
try:
    from . import CANopenConstants as coc
except (ModuleNotFoundError, ImportError):
    import CANopenConstants as coc


class SubHandler(object):
    """
    Subscription Handler. To receive events from server for a subscription.
    The handler forwards updates to it's referenced python object.
    """

    def __init__(self, obj):
        self.obj = obj

    def datachange_notification(self, node, val, data):
        """Write incoming value from the server to mirrored object

        This method passes the value to the respective descriptor which handles
        the actual writing.
        """

        if val is None or not self.obj.server.isinit:
            return

        _node_name = node.get_browse_name()
        display_name = node.get_display_name().to_string()
        if self.obj.serverWriting[display_name]:
            self.obj.serverWriting[display_name] = False
            return
        self.obj.server.cnt['Datachange events'] += 1
        if type(self.obj) is MyRegs:
            index = 0x2200 | (self.obj.n_scb << 4) | self.obj.n_pspp
            subindex = 0x10 | coc.PSPP_REGISTERS[display_name]
            if self.obj.server.od[index][subindex].attribute == coc.ATTR.RO:
                return
        elif type(self.obj) is MySCBMaster:
            index = 0x2000
            subindex = 1 + self.obj.n_scb
        else:
            return
        if self.obj.server.sdoWrite(self.obj.nodeId, index, subindex, val):
            setattr(self.obj, _node_name.Name,
                    data.monitored_item.Value.Value.Value)


class UaObject(object):
    """
    Python object which mirrors an |OPCUA| object.

    Child UA variables/properties are auto subscribed to to synchronize python
    with UA server. Python can write to children via write method, which will
    trigger an update for UA clients.

    This class redefines the :meth:`__getattribute__` and :meth:`__setattr__`
    methods so that :any:`descriptors<descriptors>` work with instance attributes. This is
    necessary because in order to mirror the address space correctly the
    attributes have to be instance attributes.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. Most
        subscriptions use 500 ms whereas here a default value of 100 ms is used
        in order to ensure that changes made by the user are applied as fast as
        possible.
    """

    def __init__(self, master, ua_node, period=100):
        self.ua_node = ua_node
        """The python respresentation of the corresponding |OPCUA| node"""
        self.logger = master.logger
        """:class:`~logging.Logger` : The main logger of the master server also
        serves as the logger for the mirror classes"""
        self.server = master.server
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodes = {}
        """:obj:`dict` : Holds references to the child nodes based on their
        browse names as keys"""
        self.b_name = ua_node.get_browse_name().Name
        """:obj:`str` : Browse Name. ``Name`` attribute of a
        :class:`~opcua.ua.uatypes.QualifiedName` object describing the browse
        name of this node"""
        self.d_name = ua_node.get_display_name().to_string()
        """:obj:`str` : Display name of this node"""

        # keep track of the children of this object (in case python needs to
        # write, or get more info from UA server)
        for _child in ua_node.get_children():
            _child_name = _child.get_browse_name()
            self.nodes[_child_name.Name] = _child

        # find all children which can be subscribed to (python object is kept
        # up to date via subscription)
        sub_children = ua_node.get_properties()
        sub_children.extend(ua_node.get_variables())

        # subscribe to properties/variables
        handler = SubHandler(self)
        sub = self.server.create_subscription(period, handler)
        sub.subscribe_data_change(sub_children)

    def write(self, attr=None):
        """Write value of mirrored object to |OPCUA| node.

        If a specific attribute isn't passed to write, write all |OPCUA|
        children.

        Currently this is unused because all the writing is handled by the
        respective descriptor objects.

        Parameters
        ----------
        attr : :obj:`str`, optional
            The attribute to write
        """
        if attr is None:
            for k, node in self.nodes.items():
                node_class = node.get_node_class()
                if node_class == ua.NodeClass.Variable:
                    node.set_value(getattr(self, k))
        # only update a specific attr
        else:
            self.nodes[attr].set_value(getattr(self, attr))

    def __str__(self):
        return f'Mirror class of node {self.d_name}.'

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if hasattr(attr, '__get__'):
            return attr.__get__(self, self.__class__)
        return attr

    def __setattr__(self, name, value):
        try:
            obj = object.__getattribute__(self, name)
        except AttributeError:
            pass
        else:
            if hasattr(obj, '__set__'):
                return obj.__set__(self, value)
        return object.__setattr__(self, name, value)


class MyPSPPADCChannels(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors all 13 |PSPP| registers. Each has a length of one byte.
    The instance attributes are created dynamically to decrease verbosity.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Chip address of the parent |PSPP| in the serial power chain
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        for ch in range(8):
            exec(f'self.Ch{ch} = None')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.n_scb = n_scb
        """:obj:`int` : Number of the |SCB| master this belongs to"""
        self.n_pspp = n_pspp
        """:obj:`int` : Chip address of the parent |PSPP| in the serial power
        chain"""
        self.serverWriting = {f'"Ch{ch}"': False for ch in range(8)}
        """:obj:`dict` : Internal status attribute describing if the server is
        currently writing to the children of this instance"""
        self.__i = 0

    def __getitem__(self, ch):
        return eval(f'self.Ch{ch}')

    def __setitem__(self, ch, val):
        exec(f'self.Ch{ch} = val')

    def __iter__(self):
        self.__i = 0
        return self

    def __next__(self):
        if self.__i < 8:
            self.__i += 1
            return self[self.__i - 1]
        raise StopIteration


class MyMonitoringData(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors a FolderType Object that contains three UInt16
    properties.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the parent |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Chip address of the |PSPP| in the serial power chain
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Temperature = None
        """:class:`UIntField` : UInt16 attribute for a |PSPP| chip
        temperature"""
        self.Voltage1 = None
        """:class:`UIntField` : UInt16 attribute for a |PSPP| chip voltage"""
        self.Voltage2 = None
        """:class:`UIntField` : UInt16 attribute for another |PSPP| chip
        voltage"""

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.n_scb = n_scb
        """:obj:`int` : Number of the |SCB| master this belongs to"""
        self.n_pspp = n_pspp
        """:obj:`int` : Chip address of the parent |PSPP| in the serial power
        chain"""
        self.serverWriting = {name: False for name in coc.PSPPMONVALS}
        """:obj:`dict` : Internal status attribute describing if the server is
        currently writing to the children of this instance"""
        self.__i = 0

    def __getitem__(self, key):
        return eval(f'self.{key}')

    def __setitem__(self, key, val):
        exec(f'self.{key} = val')

    def __iter__(self):
        self.__i = 0
        return self

    def __next__(self):
        if self.__i < len(list(coc.PSPPMONVALS)):
            self.__i += 1
            return self[coc.PSPPMONVALS[self.__i - 1]]
        raise StopIteration


class MyRegs(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors all 13 |PSPP| registers. Each has a length of one byte.
    The instance attributes are created dynamically to decrease verbosity.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the parent |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Chip address of the parent |PSPP| in the serial power chain
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        for name in coc.PSPP_REGISTERS.keys():
            exec(f'self.{name} = None')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.n_scb = n_scb
        """:obj:`int` : Number of the |SCB| master this belongs to"""
        self.n_pspp = n_pspp
        """:obj:`int` : Chip address of the parent |PSPP| in the serial power
        chain"""
        self.serverWriting = {name: False for name in coc.PSPP_REGISTERS}
        """:obj:`dict` : Internal status attribute describing if the server is
        currently writing to the children of this instance"""
        self.__i = 0

    def __getitem__(self, key):
        if isinstance(key, int):
            return eval(f'self.{list(coc.PSPP_REGISTERS.keys())[key]}')
        return eval(f'self.{key}')

    def __setitem__(self, key, val):
        if isinstance(key, int):
            exstr = f'self.{list(coc.PSPP_REGISTERS.keys())[key]} = val'
        else:
            exstr = f'self.{key} = val'
        exec(exstr)

    def __iter__(self):
        self.__i = 0
        return self

    def __next__(self):
        if self.__i < len(coc.PSPP_REGISTERS):
            self.__i += 1
            return self[self.__i - 1]
        raise StopIteration


class MyPSPP(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors a PSPPType Object. Its children are two Folders and a
    Boolean property.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the parent |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master this belongs to
    n_pspp : :obj:`int`
        Chip address of this |PSPP| in the serial power chain
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = False
        """:class:`BoolField` : Status of the |PSPP|. Its default value is
        :data:`True`."""
        self.ADCChannels = \
            MyPSPPADCChannels(master,
                              ua_node.get_child(f'{master.idx}:ADCChannels'),
                              nodeId, n_scb, n_pspp=n_pspp)
        """:class:`MyPSPPADCChannels` : Mirror a folder for |ADC| channels"""
        self.MonitoringData = \
            MyMonitoringData(master,
                             ua_node.get_child(f'{master.idx}:MonitoringData'),
                             nodeId, n_scb, n_pspp=n_pspp)
        """:class:`MyMonitoringData` : Mirroring a folder for monitoring
        data"""
        self.Regs = MyRegs(master, ua_node.get_child(f'{master.idx}:Regs'),
                           nodeId, n_scb, n_pspp=n_pspp)
        """:class:`MyRegs` : Mirroring a folder for the |PSPP| registers"""

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.n_scb = n_scb
        """:obj:`int` : Number of the |SCB| master this belongs to"""
        self.n_pspp = n_pspp
        """:obj:`int` : Chip address of this |PSPP| in the serial power
        chain"""
        self.serverWriting = {'Status': False}
        """:obj:`dict` : Internal status attribute describing if the server is
        currently writing to the children of this instance"""


class MySCBMaster(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors a |SCB| Master which is a FolderType Object and contains
    16 PSPPType Objects which are created dynamically to decrease verbosity.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the parent |DCS| Controller
    n_scb : :obj:`int`
        Number of this |SCB| master
    """

    def __init__(self, master, ua_node, nodeId, n_scb):

        # properties and variables; must mirror UA model (based on browsename!)
        self.ConnectedPSPPs = 0
        """:class:`UIntField` : Describes the value which states how many
        |PSPP| chips are connected to this |SCB| master."""
        for i in range(16):
            exec(f"self.PSPP{i} = MyPSPP(master, ua_node.get_child('"
                 f"{master.idx}:PSPP{i}'), nodeId, n_scb, i)")
        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.isinit = False
        """:obj:`bool`: If the :attr:`ConnectedPSPPs` attribute has been set
        from outside"""
        self.n_scb = n_scb
        """:obj:`int` : Number of this |SCB| master"""
        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.serverWriting = {'ConnectedPSPPs': False}
        """:obj:`dict` : Internal status attribute describing if the server is
        currently writing to the children of this instance"""
        self.__i = 0

    def __getitem__(self, key):
        return eval(f'self.PSPP{key}')

    def __iter__(self):
        self.__i = 0
        return self

    def __next__(self):
        if self.__i < 16:
            self.__i += 1
            return self[self.__i - 1]
        raise StopIteration


class MyDCSController(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This is the top-level mirror class and represents a DCSControllerType
    Object. Its direct children are some configuration values (which |PSPP|
    chips are connected, its |CAN| node id and a status boolean) and four |SCB|
    masters representing the actual hardware. The latter are created
    dynamically to decrease verbosity.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of this |DCS| Controller
    """

    def __init__(self, master, ua_node, nodeId):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = True
        """:class:`BoolField` : Status of the Controller"""
        self.NodeId = nodeId
        """:obj:`int` : |CAN| node id of this |DCS| Controller"""
        for i in range(4):
            exec(f"self.SCB{i} = MySCBMaster(master, "
                 f"ua_node.get_child('{master.idx}:SCB{i}'), nodeId, i)")

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.isinit = True
        """:obj:`bool` : If the Controller has been initialized"""
        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the |DCS| Controller"""
        self.__n = 0

    def __getitem__(self, key):
        return eval(f'self.SCB{key}')

    def __iter__(self):
        self.__n = 0
        return self

    def __next__(self):
        if self.__n < 4:
            self.__n += 1
            return self[self.__n - 1]
        raise StopIteration

class TestClass(object):
    """This class only exists for testing the mirror classes with less
    overhead than the whole server containing CANopen communication."""

    def __init__(self, logger):

        self.isinit = False

        self.logger = logger

        # setup our server
        self.server = Server()
        self.server.set_endpoint('opc.tcp://localhost:4840/')
        self.server.allow_remote_admin(True)

        # setup our own namespace, not really necessary but should as spec
        uri = "http://yourorganisation.org/DCSControllerDesign/"
        self.idx = self.server.register_namespace(uri)

        # get Objects node, this is where we should put our nodes
        self.objects = self.server.get_objects_node()

        # populating our address space; in most real use cases this should be
        # imported from UA spec XML.
        self.logger.notice('Import UA spec from xml ...')
        self.server.import_xml('dcscontrollerdesign.xml')
        self.dctni = ua.NodeId.from_string(f'ns={self.idx};i=1003')
        self.logger.info(f'{self.dctni}')
        self.logger.success('Done')


    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.server.stop()
        if isinstance(exception_value, KeyboardInterrupt):
            self.logger.warning('Received Ctrl+C event (KeyboardInterrupt).')
            return True

    def start(self):
        """Create one mirrored DCS Controller and start the OPC server"""

        self.mDC42 = self.objects.add_object(self.idx, 'DCSController42',
                                             self.dctni)

        # starting!
        self.server.start()
        sleep(1)

        # after the UA server is started initialize the mirrored object
        self.logger.notice('Initialize mirrored object ...')
        self.mDC42py = MyDCSController(self, self.mDC42, 42)
        sleep(10)   # Wait until the class is initialized
        self.logger.success('... Done.')
        self.isinit = True

        self.run()

    def run(self):
        """Do nothing"""

        while(True):
            pass


if __name__ == '__main__':
    import logging
    logger = logging.getLogger(__name__)

    with TestClass(logger) as tc:
        tc.start()
