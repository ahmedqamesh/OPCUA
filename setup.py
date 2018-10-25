#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on Sat Jul  7 13:45:04 2018

@author: Sebastian Scholz
"""

from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(name='DCSController',
      version='0.1.0',
      description='OPCUA CANopen server for DCS Controllers',
      long_description=long_description,
      long_description_content_type="text/markdown",
      classifiers=['Development Status :: 3 - Alpha',
                   'License :: Freeware',
                   'Intended Audience :: Science/Research',
                   'Programming Language :: Python :: 3.6',
                   'Topic :: Scientific/Engineering :: Physics'],
      author='Sebastian Scholz',
      author_email='sebastian.scholz@cern.ch',
      packages=find_packages(),
      install_requires=['coloredlogs', 'verboselogs', 'opcua', 'aenum',
                        'canlib'],
      include_package_data=True,
      entry_points={'console_scripts':
                    ['DCSControllerServer=dcsControllerServer.'
                     'dcsControllerServer:main',
                     'CANopenForDCSController=dcsControllerServer.'
                     'CANopenForDCSController:main']}
      )
