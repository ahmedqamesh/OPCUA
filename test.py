# -*- coding: utf-8 -*-
"""
Created on Mon Jul 23 14:29:35 2018

@author: Sebastian
"""
import analib
import time
import ctypes as ct


@analib.wrapper.dll.CBFUNC
def cbFunc(cobid, data, dlc, flag, handle):
    print('Calling callback function with the following arguments:')
    print(f'COBID: {cobid:03X}; Data: '
          f'{[f"{c:02X}" for c in ct.string_at(data, dlc)]}; DLC: {dlc}; '
          f'Flags: {flag}; Handle: {handle}')


if __name__=='__main__':

    ret = analib.wrapper.dllInfo()
    print(f'DLL version: "{ret}"')

    with analib.channel.Channel() as ch:
        ch.setCallback(cbFunc)
        print(f'State: {ch.state}')

        print('Writing example CAN message ...')
        ch.write(0x42, [1, 2, 3, 4, 5, 6, 7])

        s, m = ch.getTime()
        print(f'Time: {time.ctime(s + m / 1000000)}')
        print('Setting Time ...')
        ch.setTime()
        s, m = ch.getTime()
        print(f'Time: {time.ctime(s + m / 1000000)}')

        # print('Restarting device ...')
        # analib.wrapper.restart(ch.ipAddress)

        print('Reading messages ...')
        while True:
            try:
                cobid, data, dlc, flag, t = ch.getMessage()
                print(f'ID: {cobid:03X}; Data: {data.hex()}, DLC: {dlc}')
            except analib.CanNoMsg:
                pass
