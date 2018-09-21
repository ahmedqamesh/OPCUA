# -*- coding: utf-8 -*-
"""
Some constants for AnaGate CAN devices

:Author: Sebastian Scholz
:Contact: sebastian.scholz@cern.ch
:Organization: Bergische Universität Wuppertal
"""

CONNECT_STATES = {1: 'DISCONNECTED', 2: 'CONNECTING', 3: 'CONNECTED',
                  4: 'DISCONNECTING', 5: 'NOT_INITIALIZED'}
""":obj:`dict` : Integer connection states and their corresponding strings"""

BAUDRATES = [10000, 20000, 50000, 62500, 100000, 125000, 250000, 500000,
             1000000]
""":obj:`list` of :obj:`int` : All possible baudrates for AnaGate CAN devices
in Hertz"""
