# Python OPC UA CANopen server for DCS Controller

## Installation
This Python package requires a working [Python 3.6](https://www.python.org/ "Official Python Homepage") Installation. I recommend the usage of [Anaconda](https://anaconda.org/ "Official Anaconda Homepage") which is avaiable for all platforms and also easy to install and manage.

Make sure that your Python installation also contains [pip](https://pypi.org/project/pip/). In the top level directory of this repository (where the file setup.py lies) use it to install the package.

    $ pip install .

If you want to modify the code then use

    $ pip install -e .

## Usage
The package creates a command line tool `DCSControllerServer` so that you do not have to invoke python yourself.

## Remarks
### Linux
If you want to use a virtual channel on a Linux machine you have to may have to start it manually with the following command

    $ sudo /usr/sbin/virtualcan.sh start
