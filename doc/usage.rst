Usage
=====

Upon installation the commandline tool ``DCSControllerServer`` is created. In most cases there should be almost no configuration neccessary as it does not even have any positional arguments.

**CAN interfaces**

Choose desired CAN interface. The following options are mutually exclusive.

-A, --anagate               Use AnaGate CAN Ethernet interface
-K, --kvaser                Use Kvaser CAN interface

**OPC UA server configuration**

-E ENDPOINT, --endpoint ENDPOINT    Endpoint of the OPCUA server (default: ``opc.tcp://localhost:4840/``)
-e EDSFILE, --edsfile EDSFILE       File path of Electronic Data Sheet (EDS) (default: */path/to/source/CANControllerForPSPPv1.eds*)
-x XMLFILE, --xmlfile XMLFILE       File path of OPCUA XML design file (default: */path/to/source/dcscontrollerdesign.xml*)

**CAN settings**

-C CHANNEL, --channel CHANNEL           Number of CAN channel to use (default: 0)
-i IPADDRESS, --ipaddress IPADDRESS     IP address of the AnaGate Ethernet CAN interface (default: ``192.168.1.254``)
-b BITRATE, --bitrate BITRATE           CAN bitrate as integer in bit/s (default: 125000)

**Logging settings**

-c LEVEL, --console_loglevel LEVEL      Level of console logging (default: ``NOTICE``)
-f LEVEL, --file_loglevel LEVEL         Level of file logging (default: ``INFO``)
-d LOGDIR, --logdir LOGDIR              Directory where log files should be stored (default: */path/to/source/log/*)

Possible logging levels are:
    * NOTSET
    * SPAM
    * VERBOSE
    * DEBUG
    * INFO
    * NOTICE
    * SUCCESS
    * WARNING
    * ERROR
    * CRITICAL

**Miscellaneous**

-h, --help                  Show help message and exit
-v, --version               Show program's version string and exit

