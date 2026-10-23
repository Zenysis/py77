#!/usr/bin/env python
from setuptools import find_packages, setup

setup(
    name='zenysis-py77',
    version='0.2.1',
    license='MIT',

    provides=['pylib'],

    description='Zenysis-maintained fork of the Room 77 Python Libraries',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',

    url='https://github.com/Zenysis/py77',
    project_urls={
        'Source': 'https://github.com/Zenysis/py77',
        'Upstream': 'https://github.com/room77/py77',
    },

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
