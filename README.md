python-adb
==========
[![Coverage Status][coverage_img]][coverage_link]
[![Build Status][build_img]][build_link]

This repository contains a pure-python implementation of the ADB and Fastboot
protocols, using libusb1 for USB communications.

This is a complete replacement and rearchitecture of the Android project's [ADB
and fastboot code](https://github.com/android/platform_system_core/tree/master/adb)

This code is mainly targeted to users that need to communicate with Android
devices in an automated fashion, such as in automated testing. It does not have
a daemon between the client and the device, and therefore does not support
multiple simultaneous commands to the same device. It does support any number of
devices and _never_ communicates with a device that it wasn't intended to,
unlike the Android project's ADB.


### Using as standalone tool

Running `./make_tools.py` creates two files: `adb.zip` and `fastboot.zip`. They
can be run similar to native `adb` and `fastboot` via the python interpreter:

    python adb.zip devices
    python adb.zip shell ls /sdcard

### Using as a Python Library

A [presentation was made at PyCon 2016][pycon_preso], and here's some demo code:

```python
import os.path as op

from adb import adb_commands
from adb import sign_m2crypto


# KitKat+ devices require authentication
signer = sign_m2crypto.M2CryptoSigner(
    op.expanduser('~/.android/adbkey'))
# Connect to the device
device = adb_commands.AdbCommands()
device.ConnectDevice(
    rsa_keys=[signer])
# Now we can use Shell, Pull, Push, etc!
for i in xrange(10):
  print device.Shell('echo %d' % i)
```

### Pros

  * Simpler code due to use of libusb1 and Python.
  * API can be used by other Python code easily.
  * Errors are propagated with tracebacks, helping debug connectivity issues.
  * No daemon outliving the command.
  * Can be packaged as standalone zips that can be run independent of the CPU
    architecture (e.g. x86 vs ARM).


### Cons

  * Technically slower due to Python, mitigated by no daemon.
  * Only one command per device at a time.
  * More dependencies than Android's ADB.


### Dependencies

  * libusb1 (1.0.16+)
  * python-libusb1 (1.2.0+)
  * `adb.zip`: one of:
    * python-m2crypto (0.21.1+)
    * python-rsa (3.2+)
  * `fastboot.zip` (optional):
    * python-progressbar (2.3+)

### History

#### 1.0.0

 * Initial version

#### 1.1.0

 * Added TcpHandle (jameyhicks)
 * Various timing and other changes (alusco)


[coverage_img]: https://coveralls.io/repos/github/google/python-adb/badge.svg?branch=master
[coverage_link]: https://coveralls.io/github/google/python-adb?branch=master
[build_img]: https://travis-ci.org/google/python-adb.svg?branch=master
[build_link]: https://travis-ci.org/google/python-adb
[pycon_preso]: https://docs.google.com/presentation/d/1bv8pmm8TZp4aFxoq2ohA-ms_a3BWci7D3tYvVGIm8T0/pub?start=false&loop=false&delayms=10000
