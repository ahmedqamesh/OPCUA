#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
This module provides classes that are used to mirror an |OPCUA| address space.

The main 'magic' (parsing between |OPCUA| nodes, the mirrored objects and the
CANopen_ communication) happens inside the classes in this module. Each
object/node has a data subscription which handles most of the data exchange.

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


PERIOD_DEFAULT = 500
""":obj:`int` : Default OPC UA publish interval in milliseconds"""

class SubHandler(object):
    """
    Subscription Handler. To receive events from server for a subscription.
    The handler forwards updates to it's referenced python object.
    
    Parameters
    ----------
    obj : Child class of :class:`~UaObject`
        The mirror class of this subscription handler. This is needed for 
        reference to its value and the server.
    """

    def __init__(self, obj):
        self.obj = obj

    def datachange_notification(self, node, val, data):
        """Handle data change events coming from the server.
        
        In particular this function handles all writing.

        Parameters
        ----------
        node : :class:`~opcua.common.node.Node`
            The UA node where the value change has happened
        val
            New value of the node. In most cases this will be an unsigned
            :obj:`int`.
        data : :class:`opcua.common.subscription.DataChangeNotif`
            Contains detailed information about the subscription data and the
            monitored item.
        """
        # Check for valid data change
        if val is None or not self.obj.server.isinit:
            return
        display_name = node.get_display_name().to_string()
        mirrorval = eval(f'self.obj.{display_name}')
        # Check if data change originates from server or client
        if val == mirrorval:
            return
        nodeval = node.get_value()
        # The following check prevents problems which occur when you write the
        # same node too frequently
        if val != nodeval:
            if nodeval == mirrorval:
                node.set_value(val)
            return
        # Count the data change event
        self.obj.server.cnt['Datachange events'] += 1
        # Prepare SDO writing based on object type
        if type(self.obj) is MyRegs:
            index = 0x2200 | (self.obj.n_scb << 4) | self.obj.n_pspp
            subindex = 0x10 | coc.PSPP_REGISTERS[display_name]
            if self.obj.server.od[index][subindex].attribute == coc.ATTR.RO:
                return
        elif type(self.obj) is MySCBMaster:
            index = 0x2000
            subindex = 1 + self.obj.n_scb
        elif type(self.obj) is MyDCSController:
            if display_name == 'ADCTRIM':
                index = 0x2001
                subindex = 0
            else:
                return
        else:
            return
        # Write value to hardware and set it to UA node and python object
        if self.obj.server.sdoWrite(self.obj.nodeId, index, subindex, val):
            exec(f'self.obj.{display_name} = {val}')
            node.set_value(val)
            # setattr(self.obj, _node_name.Name,
            #         data.monitored_item.Value.Value.Value)
        else:
            node.set_value(mirrorval)


class UaObject(object):
    """
    Python object which mirrors an |OPCUA| object.

    Child UA variables/properties are auto subscribed to synchronize python
    with UA server. Python can write to children via write method, which will
    trigger an update for UA clients.

    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, period=PERIOD_DEFAULT):
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
        sub.subscribe_data_change(sub_children, queuesize=0)

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


class MyFrontend(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).
    
    This class represents one Frontend which has two monitoring values (one 
    temperature and one voltage).
    
    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    n_module : :obj:`int`
        Module number (0-15). This is not neccessarily equal to the module
        number in its serial powering chain.
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """
    
    def __init__(self, master, ua_node, nodeId, n_module, 
                 period=PERIOD_DEFAULT):
        
        # properties and variables; must mirror UA model (based on browsename!)
        self.Temperature = None
        self.Voltage = None
        
        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)
        
        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.n_module = n_module
        """:obj:`int` : Module number (0-15)"""
        
        
class MyFrontends(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).
    
    This class represents a FolderType object which contains 16 entries of
    :class:`MyFrontend`.
    
    Parameters
    ----------
    master : :class:`~.dcsControllerServer.DCSControllerServer`
        The master server providing |CAN| communication and |OPCUA|
        functionality
    ua_node
        The python respresentation of the corresponding |OPCUA| node
    nodeId : :obj:`int`
        |CAN| node id of the |DCS| Controller
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """
    
    def __init__(self, master, ua_node, nodeId, period=PERIOD_DEFAULT):
        
        # properties and variables; must mirror UA model (based on browsename!)
        for module in range(16):
            exec(f'self.Frontend{module:X} = MyFrontend(master, '
                 f'ua_node.get_child(f"{master.idx}:Frontend{module:X}"), '
                 f'nodeId, module, period=period)')
            
        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of the parent |DCS| Controller"""
        self.__i = 0
        
    def __getitem__(self, key):
        return eval(f'self.Frontend{key:X}')
    
    def __iter__(self):
        self.__i = 0
        return self
    
    def __next__(self):
        if self.__i < 16:
            self.__i += 1
            return self[self.__i - 1]
        raise StopIteration


class MyPSPPADCChannels(UaObject):
    """
    Definition of |OPCUA| object which represents a object to be mirrored in
    python. This class mirrors it's UA counterpart and semi-configures itself
    according to the UA model (generally from |XML|).

    This class mirrors all 8 |PSPP| |ADC| channels. Each has a length of 10 
    bits. The instance attributes are created dynamically to decrease 
    verbosity.

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp, 
                 period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        for ch in range(8):
            exec(f'self.Ch{ch} = None')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp,
                 period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        for key in coc.PSPPMONVALS:
            exec(f'self.{key} = None')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp,
                 period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        for name in coc.PSPP_REGISTERS.keys():
            exec(f'self.{name} = None')

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, n_pspp, 
                 period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = False
        """:obj:`bool` : Status of the |PSPP|. Its default value is
        :data:`True`."""
        self.ADCChannels = \
            MyPSPPADCChannels(master,
                              ua_node.get_child(f'{master.idx}:ADCChannels'),
                              nodeId, n_scb, n_pspp=n_pspp, period=period)
        """:class:`MyPSPPADCChannels` : Mirror a folder for |ADC| channels"""
        self.MonitoringData = \
            MyMonitoringData(master,
                             ua_node.get_child(f'{master.idx}:MonitoringData'),
                             nodeId, n_scb, n_pspp=n_pspp, period=period)
        """:class:`MyMonitoringData` : Mirroring a folder for monitoring
        data"""
        self.Regs = MyRegs(master, ua_node.get_child(f'{master.idx}:Regs'),
                           nodeId, n_scb, n_pspp=n_pspp, period=period)
        """:class:`MyRegs` : Mirroring a folder for the |PSPP| registers"""

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, n_scb, period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        self.ConnectedPSPPs = 0
        """:obj:`int` : Describes the value which states how many |PSPP| chips
        are connected to this |SCB| master."""
        for i in range(16):
            exec(f"self.PSPP{i} = MyPSPP(master, ua_node.get_child('"
                 f"{master.idx}:PSPP{i}'), nodeId, n_scb, i, period)")
        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

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
    period : :obj:`int`, optional
        Publish interval for |OPCUA| data subscription in milliseconds. 
        Defaults to :data:`PERIOD_DEFAULT`.
    """

    def __init__(self, master, ua_node, nodeId, period=PERIOD_DEFAULT):

        # properties and variables; must mirror UA model (based on browsename!)
        self.Status = True
        """:obj:`bool` : Status of the Controller"""
        self.NodeId = nodeId
        """:obj:`int` : |CAN| node id of this |DCS| Controller"""
        self.ADCTRIM = None
        """:obj:`int` : |ADC| trimming bits. This is a 6 bit entry"""
        for i in range(4):
            exec(f"self.SCB{i} = MySCBMaster(master, "
                 f"ua_node.get_child('{master.idx}:SCB{i}'), nodeId, i,"
                 f" period)")
        self.Frontends = \
            MyFrontends(master, ua_node.get_child(f'{master.idx}:Frontends'),
                        nodeId, period)
        """:class:`MyFrontends` : Folder-like mirror class containing 
        references to mirrored modules"""

        # init the UaObject super class to connect the python object to the UA
        # object.
        super().__init__(master, ua_node, period)

        self.isinit = True
        """:obj:`bool` : If the Controller has been initialized"""
        self.server = master
        """:class:`~.dcsControllerServer.DCSControllerServer` : The master
        server providing |CAN| communication and |OPCUA| functionality"""
        self.nodeId = nodeId
        """:obj:`int` : |CAN| node id of this |DCS| Controller for conformity
        with other mirror classes"""
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
    import coloredlogs
    import verboselogs
    from extend_logging import extend_logging
    
    extend_logging()
    logger = verboselogs.VerboseLogger(__name__)
    coloredlogs.install(fmt='%(asctime)s %(levelname)-8s %(message)s', 
                        level='NOTICE', isatty=True, milliseconds=True)

    with TestClass(logger) as tc:
        tc.start()
