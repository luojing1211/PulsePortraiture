#!/usr/bin/env python

from distutils.core import setup

setup(name='PulsePortraiture',
      version='0.0',
      description='Data analysis package for wideband pulsar timing',
      author='Tim Pennucci',
      author_email='tim.pennucci@nanograv.org',
      url='http://github.com/pennucci/PulsePortraiture',
      py_modules=['pplib, pptoaslib'],
      scripts=['ppalign.py','ppgauss.py', 'ppinterp.py', 'pptoas.py',
          'ppzap.py']
     )
