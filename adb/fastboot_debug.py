#!/usr/bin/env python
# Copyright 2014 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Fastboot in python.

Call it similar to how you call android's fastboot. Call it similar to how you
call android's fastboot, but this only accepts usb paths and no serials.
"""

import argparse
import inspect
import logging
import sys

from adb import common_cli
from adb import fastboot

try:
    import progressbar
except ImportError:
    # progressbar is optional.
    progressbar = None


def Devices(args):
    """Lists the available devices.

    List of devices attached
    015DB7591102001A        device
    """
    for device in fastboot.FastbootCommands.Devices():
        print('%s\tdevice' % device.serial_number)
    return 0


def _InfoCb(message):
    # Use an unbuffered version of stdout.
    if not message.message:
        return
    sys.stdout.write('%s: %s\n' % (message.header, message.message))
    sys.stdout.flush()


def main():
    common = common_cli.GetCommonArguments()
    device = common_cli.GetDeviceArguments()
    device.add_argument(
        '--chunk_kb', type=int, default=1024, metavar='1024',
        help='Size of packets to write in Kb. For older devices, it may be '
             'required to use 4.')
    parents = [common, device]

    parser = argparse.ArgumentParser(
        description=sys.modules[__name__].__doc__, parents=[common])
    subparsers = parser.add_subparsers(title='Commands', dest='command_name')

    subparser = subparsers.add_parser(
        name='help', help='Prints the commands available')
    subparser = subparsers.add_parser(
        name='devices', help='Lists the available devices', parents=[common])
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Continue)

    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Download,
        {'source_file': 'Filename on the host to push'})
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Erase)
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Flash)
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Getvar)
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Oem)
    common_cli.MakeSubparser(
        subparsers, parents, fastboot.FastbootCommands.Reboot)

    if len(sys.argv) == 1:
        parser.print_help()
        return 2

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    if args.command_name == 'devices':
        return Devices(args)
    if args.command_name == 'help':
        parser.print_help()
        return 0

    kwargs = {}
    argspec = inspect.getargspec(args.method)
    if 'info_cb' in argspec.args:
        kwargs['info_cb'] = _InfoCb
    if 'progress_callback' in argspec.args and progressbar:
        bar = progressbar.ProgessBar(
            widgets=[progressbar.Bar(), progressbar.Percentage()])
        bar.start()

        def SetProgress(current, total):
            bar.update(current / total * 100.0)
            if current == total:
                bar.finish()

        kwargs['progress_callback'] = SetProgress

    return common_cli.StartCli(
        args,
        fastboot.FastbootCommands,
        chunk_kb=args.chunk_kb,
        extra=kwargs)


if __name__ == '__main__':
    sys.exit(main())
