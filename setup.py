#!/usr/bin/env python
from setuptools import find_packages, setup

setup(
    name='pylib',
    version='0.2',
    license='MIT',

    provides=['pylib'],

    description='Room 77 Python Libraries',
    long_description=open('README.md').read(),

    url='https://github.com/room77/py77',

    packages=find_packages(),
    data_files=[
        ('pylib/zeus/utils/bash', ['pylib/zeus/utils/bash/common.sh'])
    ],
    entry_points={
        'console_scripts': [
            'zeus=pylib.zeus.zeus:main'
        ]
    }
)
