# -*- coding: utf-8 -*-
"""
Created on Mon Jul 23 11:45:30 2018

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal
"""
import os
import ctypes as ct
import sys
import platform

from .dll import libCANDLL
from .exception import DllException


def loadDLL():
    """Load AnaGate |API| libaries.

    This function handles the platform-specific stuff.

    Returns
    -------
    :obj:`ctypes.WinDLL`,  :obj:`ctypes.CDLL`
        :mod:`ctypes` library. The exact type is platform specific.

    Raises
    ------
    :exc:`ValueError`
        When platform is not Windows or Linux
    """

    f_dir = os.path.dirname(os.path.abspath(__file__))
    ext = ''
    if platform.machine().endswith('64'):
        ext = '64'
        lib_dir = os.path.join(f_dir, 'lib', 'x86_64')
    else:
        lib_dir = os.path.join(f_dir, 'lib', 'x86')

    if sys.platform.startswith('win32'):
        lib_name = f'AnaGateCan{ext}.dll'
    elif sys.platform.startswith('linux'):
        lib_name = f'libCANDLLRelease{ext}.so'
        ct.cdll.LoadLibrary(os.path.join(lib_dir, 'libAnaGateRelease.so'))
        ct.cdll.LoadLibrary(os.path.join(lib_dir, 'libAnaGateExtRelease.so'))
    else:
        raise ValueError(f'Unknown platform: {sys.platorm}')
    lib_path = os.path.join(lib_dir, lib_name)
    if sys.platform.startswith('win32'):
        return ct.WinDLL(lib_path)
    else:
        return ct.CDLL(lib_path)


dll = libCANDLL(loadDLL())


def dllInfo():
    """Determines the current version information of the AnaGate |DLL|.

    Returns
    -------
    :obj:`str`
        Version reference string of the AnaGate |DLL|.
    """
    buf = ct.create_string_buffer(128)
    nMessageLen = ct.c_int32(128)

    dll.DLLInfo(buf, nMessageLen)
    return buf.value.decode()


def errorMessage(returnCode):
    """Returns a description of the given error code as a text string.

    Returns a textual description of the parsed error code (see `Anagate API
    2.0 Manualm Appendix A, API return codes`_). If the destination buffer is
    not large enough to store the text, the text is shortened to the specified
    buffer size.

    Parameters
    ----------
    returnCode : :obj:`int`
        Error code for which the error description is to be determined.

    Returns
    -------
    :obj:`str`
        Error description.
    """
    buf = ct.create_string_buffer(128)
    buflen = ct.c_int32(128)
    nRC = ct.c_int32(returnCode)

    dll.CANErrorMessage(nRC, buf, buflen)
    return buf.value.decode()


def restart(ipAddress='192.168.1.254', timeout=10000):
    """Restarts an AnaGate |CAN| device.

    Restarts the AnaGate |CAN| device at the specified network address. It
    implicitly disconnects all open network connections to all existing |CAN|
    interfaces. The Restart command is even possible if the maximum number of
    allowed connections is reached.

    Parameters
    ----------
    ipAddress : :obj:`str`, optional
        Network address of the AnaGate partner. Defaults to `'192.168.1.254'`
        which is the factory default.
    timeout : :obj:`int`, optional
        Default timeout for accessing the AnaGate in milliseconds. A timeout is
        reported if the AnaGate partner does not respond within the defined
        timeout period. Defaults to 10 s.
    """
    ipAddress = ct.c_char_p(bytes(ipAddress, 'utf-8'))
    dll.CANRestart(ipAddress, ct.c_int32(timeout))


def errorCheck(returnCode):
    """Check return code from |API| function for error.

    For AnaGate |API| functions an error has occured when the return code is
    not 0. The error message is then constructed by an API function form this
    return code.

    Parameters
    ----------
    returnCode : :obj:`int`
        The integer returns code from the AnaGate |API| function

    Returns
    -------
    :obj:`bool`
        True only if the return code is 0.

    Raises
    ------
    :exc:`~.exception.DllException`
        When the API function returned an error.
    """
    if returnCode == 0:
        return True
    else:
        raise DllException(errorMessage(returnCode))
