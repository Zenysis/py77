# Room 77 Python Libraries
This is a collection of Python libraries used at Room 77, Inc.

This is a fork maintained by Zenysis, since the original
[room77/py77](https://github.com/room77/py77) is no longer maintained.

## Installation
Install from PyPI:

    pip install zenysis-py77

The package is still imported as `pylib` and installs the `zeus` command.

Alternatively, clone the repo and include its path in your PYTHONPATH

For example:

  export PYTHONPATH=${PYTHONPATH}:/home/user/src/pylib


Many of the pylib libraries can be used immediately without installing dependencies. The stable-requirements has not been cleaned and contains more dependencies than are necessary. The recommended approach is to not install the stable-requirements and attempt to use the library as is. Only install the requirements when they are needed.

There is one additional dependency not in PyPi: GraphViz. To install the necessary Python bindings run

    sudo apt-get install libgv-python

Or the equivalent command for your operating system. Depending on your environment, it may be necessary to add the installed module to your Python path either by setting the PYTHONPATH environment variable or by creating symlinks to the installed module and shared library. On Debian, by default, `gv.py` and `_gv.so` are installed to `/usr/share/pyshared`.

A `setup.py` file has been provided but is in experimental state. It is not recommended to install this way if you want to use `flash`

## Components

### Flash
A declarative build system.

### Zeus
A task runner.

### Master Packaging System
A production deployment system.

## License
All code is distributed under the MIT license, unless otherwise noted. See LICENSE for details.