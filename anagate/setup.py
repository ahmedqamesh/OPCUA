from setuptools import setup

setup(name='anagate',
      version='0.1.0',
      description='DLL wrapper for anagate devices',
      classifiers=['Development Status :: 3 - Alpha',
                   'License :: Freeware',
                   'Intended Audience :: Science/Research',
                   'Programming Language :: Python :: 3',
                   'Topic :: Scientific/Engineering :: Physics'],
      author='Sebastian Scholz',
      author_email='sebastian.scholz@cern.ch',
      packages=['analib'],
      install_requires=['canlib'],
      include_package_data=True
      )
