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


def check_uint(value, bitlength=64):
    """Check if a value is an unsigned integer of a specified length

    Parameters
    ----------
    value
        The Value to check
    bitlength : :obj:`int`, optional
        Maximum number of bits that the value must stick to.

    Returns
    -------
    :obj:`bool`
        If the value fulfills the conditions

    Raises
    ------
    :exc:`TypeError`
        If the value is not an integer
    :exc:`ValueError`
        If the value exceeds the given range
    """
    if value is None:
        return True
    elif not isinstance(value, int):
        raise TypeError(f'Expecting integer and not '
                        f'{value.__class__.__name__}.')
    elif value not in range(2**bitlength):
        raise ValueError(f'Value must be between 0 and 2**{bitlength}, but it '
                         f'is {value}.')
    return True


def check_bool(value):
    """Check if a value is a :obj:`bool`

    Parameters
    ----------
    value
        The Value to check

    Returns
    -------
    :obj:`bool`
        If the value fulfills the conditions

    Raises
    ------
    :exc:`TypeError`
        If the value is not a bool
    """
    if value is not None and not isinstance(value, bool):
        raise TypeError(f'Expecting bool and not '
                        f'{value.__class__.__name__}.')
    return True


def pspp_index(n_scb, n_pspp):
    """Get |OD| main index of a |PSPP| chip

    Parameters
    ----------
    n_scb : :obj:`int`
        |SCB| master number (0-3)
    n_pspp : :obj:`int`
        Number of the |PSPP| in its |SCB| chain (0-15)

    Returns
    -------
    :obj:`int`
        Object Dictionary main index of |PSPP|
    """
    return 0x2200 + 16 * n_scb + n_pspp


def get_address(name, n_scb=None, n_pspp=None, inst=None):
    """Get object dictionary address based on the name.

    Parameters
    ----------
    name : :obj:`str`
        Attribute name
    n_scb : :obj:`int`
        |SCB| master number (0-3)
    n_pspp : :obj:`int`
        Number of the |PSPP| in its SCB chain (0-15)
    inst
        The descriptor object calling this method. Needed to distinguish
        between nodes that have the same display names.

    Returns
    -------
    index : :obj:`int`
        |OD| index or None if name does not fit
    subindex : :obj:`int`
        |OD| subindex or None if name does not fit
    """
    index, subindex = None, None
    if name is 'ConnectedPSPPs':
        index = 0x2000
        subindex = n_scb + 1
    elif name in coc.PSPP_REGISTERS.keys():
        index = pspp_index(n_scb, n_pspp)
        subindex = 0x10 + coc.PSPP_REGISTERS[name]
    elif name in coc.PSPPMONVALS:
        index = pspp_index(n_scb, n_pspp)
        subindex = 1
    elif name is 'Status':
        if inst.parent.__class__.__name__ is 'MyPSPP':
            index = pspp_index(n_scb, n_pspp)
            subindex = 2
    elif name in [f'Ch{i}' for i in range(8)]:
        index = pspp_index(n_scb, n_pspp)
        subindex = 0x20 + int(name.strip('Ch'))
    return index, subindex


class UIntField(object):
    """Descriptor class for an unsigned integer of variable bit length.

    The setter checks if the value is None or a valid integer.

    Parameters
    ----------
    parent
        Points to the parent object in attribute hierarchy
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master class providing |CAN| communication and |OPCUA| functionality.
    name : :obj:`str`
        Name of this :class:`UIntField`. Needed to make the connection to the
        object dictionary.
    nodeId : :obj:`int`, optional
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`, optional
        Number of the |SCB| master if this belongs to one
    bitlength : :obj:`int`, optional
        Defines maximum size. Defaults to 64 bits.
    val : :obj:`int`, optional
        Initial value
    n_pspp : :obj:`int`, optional
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, parent, master, name, nodeId, n_scb=None,
                 bitlength=64, val=None, n_pspp=None):
        self.parent = parent
        self.master = master
        self.logger = master.logger
        self.server = master.server
        self.name = name
        self.bitlength = bitlength
        """:obj:`int` : Maximum length in bits of this unsigned integer"""
        self.val = val
        """:obj:`int` : Actual value of the attribute"""
        self.nodeId = nodeId
        self.n_scb = n_scb
        self.n_pspp = n_pspp
        self.index, self.subindex = get_address(name, n_scb, n_pspp)
        self.valid_entry = self.index is not None and self.subindex is \
            not None
        self.acc_attr = None
        if self.valid_entry:
            self.acc_attr = master.od[self.index][self.subindex].attribute
        self.justread = False


    def __get__(self, obj, objtype):
        self.logger.info(f'Invoking getter on {obj}{self.name}.')
        if self.master.isinit and self.valid_entry:
            val = self.master.sdo_read(self.nodeId, self.index, self.subindex)
            if val is not None:
                self.justread = True
                self.val = int.from_bytes(val, 'little')
                self.logger.info(f'Got value {self.val:X}.')
                nd = self.parent.ua_node
                if self.name in coc.PSPPMONVALS.keys():
                    vals = [(self.val >> i * 10) & (2**10 - 1)
                            for i in range(3)]
                    for i in range(len(coc.PSPPMONVALS.keys())):
                        name = list(coc.PSPPMONVALS.keys())[i]
                        chnd = nd.get_child(f'{self.master.idx}:{name}')
                        chnd.set_value(vals[i])
                else:
                    chnd = nd.get_child(f'{self.master.idx}:{self.name}')
                    chnd.set_value(self.val)
        return self.val

    def __set__(self, obj, val):
        if val is not None:
            self.logger.info(f'Invoking setter on {obj}{self.name} with '
                             f'value {val:X}.')
        check_uint(val, self.bitlength)
        if val is not None and self.master.isinit and self.valid_entry \
                and self.acc_attr in [coc.ATTR.WO, coc.ATTR.RW] and not \
                self.justread:
            if self.master.sdo_write(self.nodeId, self.index,
                                     self.subindex, val):
                self.val = val
                if self.name is 'ConnectedPSPPs':
                    for i in range(16):
                        exec(f'self.parent.PSPP{i}.Status = '
                             'bool((val >> i) & 1)')
                    self.parent.isinit = True
        else:
            self.val = val
            self.justread = False

    def __set_name__(self, owner, name):
        self.name = name


class BoolField(object):
    """Descriptor class for a boolean.

    The setter checks if the value is :data:`None` or a :obj:`bool`.

    Parameters
    ----------
    parent
        Points to the parent object in attribute hierarchy
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master class providing |CAN| communication and |OPCUA|
        functionality
    name : :obj:`str`
        Name of this :class:`BoolField`. Needed to make the connection to the
        object dictionary
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`, optional
        Number of the |SCB| master if this belongs to one
    val : :obj:`bool`, optional
        Initial value
    n_pspp : :obj:`int`, optional
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, parent, master, name, nodeId, n_scb=None, val=None,
                 n_pspp=None):
        self.parent = parent
        self.master = master
        self.logger = master.logger
        self.server = master.server
        self.name = name
        self.val = val
        """:obj:`bool` : Actual value of the attribute"""
        self.nodeId = nodeId
        self.n_scb = n_scb
        self.n_pspp = n_pspp
        self.index, self.subindex = get_address(name, n_scb, n_pspp, self)
        self.valid_entry = self.index is not None and self.subindex is \
            not None
        self.acc_attr = None
        if self.valid_entry:
            self.acc_attr = master.od[self.index][self.subindex].attribute
        self.justread = False

    def __get__(self, obj, objtype):
        self.logger.info(f'Invoking getter on {obj}{self.name}.')
        if self.master.isinit and self.valid_entry:
            val = self.master.sdo_read(self.nodeId, self.index, self.subindex)
            if val is not None:
                self.justread = True
                self.val = bool(int.from_bytes(val, 'little'))
                self.logger.info(f'Got value {self.val}.')
                nd = self.parent.ua_node
                chnd = nd.get_child(f'{self.master.idx}:{self.name}')
                chnd.set_value(self.val)
        return self.val

    def __set__(self, obj, val):
        if val is not None:
            self.logger.info(f'Invoking setter on {obj}{self.name} with '
                             f'value {val}.')
        check_bool(val)
        if val is not None and self.master.isinit and self.valid_entry \
                and self.acc_attr in [coc.ATTR.WO, coc.ATTR.RW] and not \
                self.justread:
            if self.master.sdo_write(self.nodeId, self.index, self.subindex,
                                     val) or self.name == 'Status':
                self.val = val
        else:
            self.val = val
            self.justread = False

    def __set_name__(self, owner, name):
        self.name = name


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
        # print("Python: New data change event", node, val, data)

        _node_name = node.get_browse_name()
        # display_name = node.get_display_name().to_string()
        setattr(self.obj, _node_name.Name,
                data.monitored_item.Value.Value.Value)


class UaObject(object):
    """
    Python object which mirrors an |OPCUA| object.

    Child UA variables/properties are auto subscribed to to synchronize python
    with UA server. Python can write to children via write method, which will
    trigger an update for UA clients.

    This class redefines the :meth:`__getattribute__` and :meth:`__setattr__`
    methods so that descriptors work with instance attributes. This is
    necessary because in order to mirror the address space correctly the
    attributes have to be instance attributes.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    """

    def __init__(self, master, ua_node):
        self.ua_node = ua_node
        self.logger = master.logger
        self.server = master.server
        self.nodes = {}
        self.b_name = ua_node.get_browse_name().Name
        self.d_name = ua_node.get_display_name().to_string()

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
        sub = self.server.create_subscription(500, handler)
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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        for i in range(8):
            exec(f'self.Ch{i} = UIntField(self, master, "Ch{i}", nodeId, '
                 f'n_scb, 16, n_pspp=n_pspp)')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)


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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Temperature = UIntField(self, master, 'Temperature', nodeId,
                                     n_scb, 16, n_pspp=n_pspp)
        """:class:`UIntField` : UInt16 attribute for a |PSPP| chip
        temperature"""
        self.Voltage1 = UIntField(self, master, 'Voltage1', nodeId, n_scb, 16,
                                  n_pspp=n_pspp)
        """:class:`UIntField` : UInt16 attribute for a |PSPP| chip voltage"""
        self.Voltage2 = UIntField(self, master, 'Voltage2', nodeId, n_scb, 16,
                                  n_pspp=n_pspp)
        """:class:`UIntField` : UInt16 attribute for another |PSPP| chip
        voltage"""

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)


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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        for name in coc.PSPP_REGISTERS.keys():
            exec(f'self.{name} = UIntField(self, master, name, nodeId, '
                 f'n_scb, 8, n_pspp=n_pspp)')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)


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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    n_pspp : :obj:`int`
        Number of the |PSPP| in the serial power chain if this belongs to a
        |PSPP|.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = BoolField(self, master, 'Status', nodeId, n_scb, False,
                                n_pspp)
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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_scb : :obj:`int`
        Number of the |SCB| master if this belongs to one
    """

    def __init__(self, master, ua_node, nodeId, n_scb):

        # properties and variables; must mirror UA model (based on browsename!)
        self.ConnectedPSPPs = UIntField(self, master, 'ConnectedPSPPs', nodeId,
                                        n_scb, 16, 0)
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
        self.__number = n_scb

    @property
    def number(self):
        """:obj:`int` : Number of this |SCB| master (0-3)"""
        return self.__number


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
        The master class providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    """

    def __init__(self, master, ua_node, nodeId):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = BoolField(self, master, 'Status', nodeId, val=False)
        """:class:`BoolField` : Status of the Controller"""
        self.__NodeId = nodeId
        for i in range(4):
            exec(f"self.SCB{i} = MySCBMaster(master, "
                 f"ua_node.get_child('{master.idx}:SCB{i}'), nodeId, i)")

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node)

        self.isinit = True
        """:obj:`bool` : If the Controller has been initialized"""
        self.master = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        class providing |CAN| communication and |OPCUA| functionality"""

    @property
    def NodeId(self):
        """:obj:`int`: The |CAN| node id of the |DCS| Controller takes a value
        between 1 and 127."""
        return self.__NodeId

    @NodeId.setter
    def NodeId(self, value):
        if value not in range(1, 128) and self.master.isinit:
            raise ValueError(f'Valid node ids are 1-127 and not {value}.')
        self.__NodeId = value


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
