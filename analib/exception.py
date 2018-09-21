# -*- coding: utf-8 -*-
"""
Some basic custom exceptions which do nothing special

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal
"""

class AnalibException(Exception):
    """Base class for all exceptions in analib"""
    pass


class DllException(AnalibException):
    """Base class for exceptions from dll calls in analib

    All instances of this class must have a `rc` attribute defined (this is
    enforced in :func:`~.DllException.__init__()`). Its value is the return
    code from the |API| function.
    """

    @staticmethod
    def _get_error_text(rc):
        # import here to prevent circular imports
        from .wrapper import errorMessage
        return errorMessage(rc)

    def __init__(self, rc):
        self.rc = rc
        """:obj:`int` : Return code from the |API| function"""
        super(DllException, self).__init__(self._get_error_text(self.rc))


class CanNoMsg(AnalibException):
    """Raised if there are no CAN messages in the message queue"""
    pass

