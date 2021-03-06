# -*- coding: utf-8 -*-
"""
This module contains definitions that are specific for the used library.

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal
"""

import ctypes as ct

from . import dllLoader
from .exception import DllException


_no_errcheck = dllLoader.no_errcheck


class libCANDLL(dllLoader.MyDll):
    """This class contains all the prototypes from the used |API|"""

    CBFUNC = ct.CFUNCTYPE(ct.c_void_p, ct.c_int32, ct.POINTER(ct.c_char),
                          ct.c_int32, ct.c_int32, ct.c_int32)
    """Function type for callback functions"""
    CBFUNCEX = ct.CFUNCTYPE(ct.c_void_p, ct.c_int32, ct.POINTER(ct.c_char),
                            ct.c_int32, ct.c_int32, ct.c_int32, ct.c_int32,
                            ct.c_int32)
    """Function type for callback functions which use the timestamp"""

    function_prototypes = {
        'DLLInfo': [[ct.c_char_p, ct.c_int32], ct.c_int32, _no_errcheck],
        'CANOpenDevice': [[ct.POINTER(ct.c_int32), ct.c_int32,
                           ct.c_int32, ct.c_int32, ct.c_char_p, ct.c_int32]],
        'CANOpenDeviceEx': [[ct.POINTER(ct.c_int32), ct.c_int32,
                           ct.c_int32, ct.c_int32, ct.c_char_p, ct.c_int32,
                           ct.c_int32]],
        'CANCloseDevice': [[ct.c_int32]],
        'CANSetGlobals': [[ct.c_int32, ct.c_uint32, ct.c_uint8,
                           ct.c_int32, ct.c_int32, ct.c_int32]],
        'CANGetGlobals': [[ct.c_int32, ct.POINTER(ct.c_uint32),
                           ct.POINTER(ct.c_uint8), ct.POINTER(ct.c_uint32),
                           ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint32)]],
        'CANSetFilter': [[ct.c_int32, ct.POINTER(ct.c_uint32)]],
        'CANGetFilter': [[ct.c_int32, ct.POINTER(ct.c_uint32)]],
        'CANSetTime': [[ct.c_int32, ct.c_uint32, ct.c_uint32]],
        'CANGetTime': [[ct.c_int32, ct.POINTER(ct.c_int32),
                        ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint32)]],
        'CANWrite': [[ct.c_int32, ct.c_int32, ct.c_char_p,
                      ct.c_int32, ct.c_int32]],
        'CANWriteEx': [[ct.c_int32, ct.c_int32, ct.c_char_p,
                      ct.c_int32, ct.c_int32, ct.POINTER(ct.c_int32),
                      ct.POINTER(ct.c_int32)]],
        'CANSetCallback': [[ct.c_int32, CBFUNC]],
        'CANSetCallbackEx': [[ct.c_int32, CBFUNCEX]],
        'CANSetMaxSizePerQueue': [[ct.c_int32, ct.c_uint32]],
        'CANGetMessage': [[ct.c_int32, ct.POINTER(ct.c_uint32),
                           ct.POINTER(ct.c_int32), ct.c_char_p,
                           ct.POINTER(ct.c_uint8), ct.POINTER(ct.c_int32),
                           ct.POINTER(ct.c_int32), ct.POINTER(ct.c_int32)],
                          ct.c_int32],
        'CANReadDigital': [[ct.c_int32, ct.POINTER(ct.c_uint32),
                            ct.POINTER(ct.c_uint32)]],
        'CANWriteDigital': [[ct.c_int32, ct.c_uint32]],
        # TODO: Include array
        'CANReadAnalog': [[ct.c_int32, ct.POINTER(ct.c_uint32),
                           ct.POINTER(ct.c_uint32 * 4),
                           ct.POINTER(ct.c_uint16)]],
        'CANWriteAnalog': [[ct.c_int32, ct.c_uint32 * 4, ct.c_uint16]],
        'CANRestart': [[ct.c_char_p, ct.c_int32]],
        'CANDeviceConnectState': [[ct.c_int32], ct.c_int32, _no_errcheck],
        'CANErrorMessage': [[ct.c_int32, ct.c_char_p, ct.c_int32], ct.c_int32,
                            _no_errcheck]
        }
    """:obj:`dict` : Function prototypes.

    One entry has the following form:

        ``'dllFunctionName': [[typeOfArg1, typeOfArg2, ...],
        errorCheckFunction, returnType]``

    All types are :mod:`ctypes` classes. It is possible to omit the return type
    and the name of the error-check function if you have suitable default
    values defined in the :meth:`__init__` method.
    """

    def __init__(self, ct_dll):
        # set default values for function_prototypes
        self.default_restype = ct.c_int32
        self.default_errcheck = self._error_check
        super(libCANDLL, self).__init__(ct_dll, **self.function_prototypes)

    def _error_check(self, result, func, arguments):
        """Default error function used in :mod:`ctype` calls for :mod:`canlib`
        |DLL|.

        Raises
        ------
        :exc:`~.exception.DllException`
            If the return code from an |API| function does not equal 0.
        """
        if result != 0:
            raise DllException(result)
        else:
            return result