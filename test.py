# -*- coding: utf-8 -*-
"""
Created on Mon Jul 23 14:29:35 2018

@author: Sebastian
"""
import analib
import time
import ctypes as ct
import random
import logging
import coloredlogs
import verboselogs
from dcsControllerServer.extend_logging import extend_logging

extend_logging()
verboselogs.install()
logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')
coloredlogs.install(fmt='%(asctime)s %(levelname)-8s %(message)s', 
                    level='DEBUG', isatty=True, milliseconds=True)

@analib.wrapper.dll.CBFUNC
def cbFunc(cobid, data, dlc, flag, handle):
    # print('Calling callback function with the following arguments:')
    logger.info(f'COBID: {cobid:03X}; Data: '
                f'{[f"{c:02X}" for c in ct.string_at(data, dlc)]}')


if __name__=='__main__':

    ret = analib.wrapper.dllInfo()
    logger.info(f'DLL version: "{ret}"')

    with analib.channel.Channel() as ch:
        ch.setCallback(cbFunc)
        logger.info(f'State: {ch.state}')

        # Test CAN message writing
        logger.info('Writing example CAN message ...')
        ch.write(0x42, [1, 2, 3, 4, 5, 6, 7])

        # Test time
        s, m = ch.getTime()
        logger.info(f'Time: {time.ctime(s + m / 1000000)}')
        logger.info('Setting Time ...')
        # ch.setTime()
        # s, m = ch.getTime()
        # print(f'Time: {time.ctime(s + m / 1000000)}')

        # Test restarting
        # print('Restarting device ...')
        # analib.wrapper.restart(ch.ipAddress)

        # Test digital input and output bits
        logger.info(f'Input bits: {ch.inputBits}')
        logger.info(f'Ouput bits: {ch.outputBits}')
        # Setting output bits
        val = random.randrange(16)
        logger.info(f'Setting output bits to {val}')
        ch.outputBits = val
        logger.info(f'Ouput bits: {ch.outputBits}')

        # Test measuring of power supply
        logger.info(f'Power supply: {ch.powerSupply} mV')

        # Analog Inputs
        logger.info(f'Analog inputs in mV: {ch.analogInputs}')

        # Analog outputs
        logger.info('Writing analog outputs')
        ch.writeAnalog([100, 200, 300, 400])
        
        logger.info('Writing messages ...')
        for i in [x.to_bytes(8, 'little') for x in range(0x100)]:
            ch.write(0x700, i)
            # time.sleep(0.04)
            ch.write(0x600, [0x40, 0x00, 0x10, 0x00, 0, 0, 0, 0])
            ch.write(0x600, [0x40, 0x00, 0x18, 0x01, 0, 0, 0, 0])
        ch.write(0x600, [0x40, 0x00, 0x18, 0x01, 0, 0, 0, 0])
        time.sleep(1)
        ch.write(0x600, [0x40, 0x00, 0x18, 0x01, 0, 0, 0, 0])

        logger.info('Reading messages ...')
        while True:
            try:
                cobid, data, dlc, flag, t = ch.getMessage()
                logger.info(f'ID: {cobid:03X}; Data: {data.hex()}, DLC: {dlc}')
            except analib.CanNoMsg:
                pass
            except KeyboardInterrupt:
                break
