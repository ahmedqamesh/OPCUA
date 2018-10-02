# Python OPC UA CANopen server for DCS Controller

This Python package provides a command line tool which starts an [OPC UA](https://opcfoundation.org/about/opc-technologies/opc-ua/) server for the [<abbr title="Detector Control System">DCS</abbr>](https://twiki.cern.ch/twiki/bin/viewauth/Atlas/DetectorControlSystemMainPage "Only accessible with CERN account") Controller. It communicates with a <abbr title="Controller Area Network">CAN</abbr> interface and talks CANopen with connected DCS Controllers. Currently only CAN interfaces from [AnaGate](https://www.anagate.de/) (Ethernet) and [Kvaser](https://www.kvaser.com/) (USB) are supported.

Some documentation is available on https://opcuacanopenfordcscontroller.readthedocs.io/en/latest/.

## Installation
This Python package requires a working [Python 3.6](https://www.python.org/ "Official Python Homepage") Installation. I recommend the usage of [Anaconda](https://anaconda.org/ "Official Anaconda Homepage") which is available for all platforms and also easy to install and manage.

Make sure that your Python installation also contains [pip](https://pypi.org/project/pip/). In the top level directory of this repository (where the file setup.py lies) use it to install the package.

    $ pip install .

If you want to modify the code then use

    $ pip install -e .
    
## Dependencies
All third-party Python packages that are needed are installed on-the-fly so you do not need to worry about these. The necessary AnaGate libraries are also included in this repository. For the use of Kvaser CAN interfaces you have to install the [Kvaser drivers](https://www.kvaser.com/downloads-kvaser/ "Kvaser download page") first which are avaiable for [Windows](https://www.kvaser.com/downloads-kvaser/?utm_source=software&utm_ean=7330130980013&utm_status=latest) and [Linux](https://www.kvaser.com/downloads-kvaser/?utm_source=software&utm_ean=7330130980754&utm_status=latest).

## Usage
The package creates a command line tool `DCSControllerServer` so that you do not have to invoke python yourself. It provides several options for configuration.
```
$ DCSControllerServer -h
usage: DCSControllerServer [-h] [-i INTERFACE] [-E ENDPOINT] [-e EDSFILE]
                           [-x XMLFILE] [-C CHANNEL] [-c CONSOLE_LOGLEVEL]
                           [-f FILE_LOGLEVEL] [-v]

OPCUA CANopen server for DCS Controller

optional arguments:
  -h, --help            show this help message and exit
  -i INTERFACE, --interface INTERFACE
                        Vendor of the CAN interface. Possible values
                        are"Kvaser" (default) and "AnaGate" (case-sensitive)
  -E ENDPOINT, --endpoint ENDPOINT
                        Endpoint of the OPCUA server
  -e EDSFILE, --edsfile EDSFILE
                        File path of Electronic Data Sheet (EDS)
  -x XMLFILE, --xmlfile XMLFILE
                        File path of OPCUA XML design file
  -C CHANNEL, --channel CHANNEL
                        Number of CAN channel to use
  -c CONSOLE_LOGLEVEL, --console-loglevel CONSOLE_LOGLEVEL
                        Level of console logging
  -f FILE_LOGLEVEL, --file-loglevel FILE_LOGLEVEL
                        Level of file logging
  -v, --version         show program's version number and exit

For more information contact sebastian.scholz@cern.ch
```
### AnaGate
If you are using an AnaGate Ethernet CAN interface you will probably need to manually set the IP address of your network card so that the interface is part of its network. The default IP address of an AnaGate CAN interface is *192.168.1.254*, so you should set the IP address of your network card to *192.168.1.1*.

## Remarks
Although a Python program should be platform-independent, some things behave differently due to unequal behaviour of the drivers.
### Linux
If you want to use a virtual channel on a Linux machine you have to may have to start it manually with the following command

    $ sudo /usr/sbin/virtualcan.sh start

It has happened that the USB port was not correctly reset after the Kvaser interface has been disconnected so that the connection to other USB devices could not be established. As a workaround a recommend rebooting the system.
