#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on Sat Jul  7 13:45:04 2018

@author: Sebastian Scholz
"""

from setuptools import setup

from dcsControllerServer.__init__ import __version__

setup(name='dcsControllerServer',
      version=__version__,
      description='OPCUA CANopen server for DCS Controllers',
      classifiers=['Development Status :: 3 - Alpha',
                   'License :: Freeware',
                   'Intended Audience :: Science/Research',
                   'Programming Language :: Python :: 3.6',
                   'Topic :: Scientific/Engineering :: Physics'],
      author='Sebastian Scholz',
      author_email='sebastian.scholz@cern.ch',
      packages=['dcsControllerServer'],
      install_requires=['coloredlogs', 'verboselogs', 'opcua', 'aenum',
                        'canlib'],
      include_package_data=True,
      entry_points={'console_scripts':
                    ['DCSControllerServer=dcsControllerServer.'
                     'dcsControllerServer:main',
                     'CANopenForDCSController=dcsControllerServer.'
                     'CANopenForDCSController:main']}
      )
