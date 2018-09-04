# -*- coding: utf-8 -*-
"""
Created on Thu Jun 28 23:40:11 2018

@author: Sebastian Scholz
"""

import coloredlogs as cl

# Platform dependent imports
if cl.WINDOWS:
    from win32gui import GetWindowText, GetForegroundWindow


def extend_logging():
    """Some extras for users of the Anaconda Prompt on Windows.

    This customizes the coloredlogs module so that bold fonts are displayed
    correctly. Note that detects the usage of the Anaconda Prompt via its
    window title.
    """
    if cl.WINDOWS:
        SPYDER = GetWindowText(GetForegroundWindow()).startswith('Spyder')
        if SPYDER:
            print('Spyder detected!')
        cl.NEED_COLORAMA = not SPYDER
        ANACONDA = GetWindowText(GetForegroundWindow()).startswith('Anaconda')
        if ANACONDA:
            print('Anaconda detected!')
        cl.CAN_USE_BOLD_FONT = not cl.NEED_COLORAMA or ANACONDA
        cl.DEFAULT_FIELD_STYLES['levelname']['bold'] = cl.CAN_USE_BOLD_FONT
        cl.DEFAULT_LEVEL_STYLES['success']['bold'] = cl.CAN_USE_BOLD_FONT
        cl.DEFAULT_LEVEL_STYLES['critical']['bold'] = cl.CAN_USE_BOLD_FONT


def removeAllHandlers(logger):
    """Ensure that all existing FileHandlers are removed.

    When errors during initialisation appear the Handlers may not removed and
    still be present in the next run. This method cleanes up any Handlers that
    may have survived.

    Args:
        logger (Logger): The Logger object from which all Handlers are removed.
    """
    while len(logger.handlers) > 0:
        h = logger.handlers[0]
        logger.removeHandler(h)


if __name__ == '__main__':
    import logging
    import verboselogs

    extend_logging()
    verboselogs.install()

    logger = logging.getLogger(__name__)
    # print(cl.NEED_COLORAMA)

    cl.install(isatty=True)

    logger.notice('This is a notice.')
    logger.success('This was a success.')

