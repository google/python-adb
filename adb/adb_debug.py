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

"""Daemon-less ADB client in python."""

import argparse
import functools
import logging
import os
import stat
import sys
import time

from adb import adb_commands
from adb import common_cli

try:
    from adb import sign_m2crypto

    rsa_signer = sign_m2crypto.M2CryptoSigner
except ImportError:
    try:
        from adb import sign_pythonrsa

        rsa_signer = sign_pythonrsa.PythonRSASigner.FromRSAKeyPath
    except ImportError:
        try:
            from adb import sign_pycryptodome

            rsa_signer = sign_pycryptodome.PycryptodomeAuthSigner
        except ImportError:
            rsa_signer = None


def Devices(args):
    """Lists the available devices.

    Mimics 'adb devices' output:
      List of devices attached
      015DB7591102001A        device        1,2
    """
    for d in adb_commands.AdbCommands.Devices():
        if args.output_port_path:
            print('%s\tdevice\t%s' % (
                d.serial_number, ','.join(str(p) for p in d.port_path)))
        else:
            print('%s\tdevice' % d.serial_number)
    return 0


def List(device, device_path):
    """Prints a directory listing.

    Args:
      device_path: Directory to list.
    """
    files = device.List(device_path)
    files.sort(key=lambda x: x.filename)
    maxname = max(len(f.filename) for f in files)
    maxsize = max(len(str(f.size)) for f in files)
    for f in files:
        mode = (
                ('d' if stat.S_ISDIR(f.mode) else '-') +
                ('r' if f.mode & stat.S_IRUSR else '-') +
                ('w' if f.mode & stat.S_IWUSR else '-') +
                ('x' if f.mode & stat.S_IXUSR else '-') +
                ('r' if f.mode & stat.S_IRGRP else '-') +
                ('w' if f.mode & stat.S_IWGRP else '-') +
                ('x' if f.mode & stat.S_IXGRP else '-') +
                ('r' if f.mode & stat.S_IROTH else '-') +
                ('w' if f.mode & stat.S_IWOTH else '-') +
                ('x' if f.mode & stat.S_IXOTH else '-'))
        t = time.gmtime(f.mtime)
        yield '%s %*d %04d-%02d-%02d %02d:%02d:%02d %-*s\n' % (
            mode, maxsize, f.size,
            t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec,
            maxname, f.filename)


@functools.wraps(adb_commands.AdbCommands.Logcat)
def Logcat(device, *options):
    return device.Logcat(
        device, ' '.join(options), timeout_ms=0)


def Shell(device, *command):
    """Runs a command on the device and prints the stdout.

    Args:
      command: Command to run on the target.
    """
    if command:
        return device.StreamingShell(' '.join(command))
    else:
        # Retrieve the initial terminal prompt to use as a delimiter for future reads
        terminal_prompt = device.InteractiveShell()
        print(terminal_prompt.decode('utf-8'))

        # Accept user input in a loop and write that into the interactive shells stdin, then print output
        while True:
            cmd = input('> ')
            if not cmd:
                continue
            elif cmd == 'exit':
                break
            else:
                stdout = device.InteractiveShell(cmd, strip_cmd=True, delim=terminal_prompt, strip_delim=True)
                if stdout:
                    if isinstance(stdout, bytes):
                        stdout = stdout.decode('utf-8')
                        print(stdout)

        device.Close()


def main():
    common = common_cli.GetCommonArguments()
    common.add_argument(
        '--rsa_key_path', action='append', default=[],
        metavar='~/.android/adbkey',
        help='RSA key(s) to use, use multiple times to load mulitple keys')
    common.add_argument(
        '--auth_timeout_s', default=60., metavar='60', type=int,
        help='Seconds to wait for the dialog to be accepted when using '
             'authenticated ADB.')
    device = common_cli.GetDeviceArguments()
    parents = [common, device]

    parser = argparse.ArgumentParser(
        description=sys.modules[__name__].__doc__, parents=[common])
    subparsers = parser.add_subparsers(title='Commands', dest='command_name')

    subparser = subparsers.add_parser(
        name='help', help='Prints the commands available')
    subparser = subparsers.add_parser(
        name='devices', help='Lists the available devices', parents=[common])
    subparser.add_argument(
        '--output_port_path', action='store_true',
        help='Outputs the port_path alongside the serial')

    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.Install)
    common_cli.MakeSubparser(subparsers, parents, adb_commands.AdbCommands.Uninstall)
    common_cli.MakeSubparser(subparsers, parents, List)
    common_cli.MakeSubparser(subparsers, parents, Logcat)
    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.Push,
        {'source_file': 'Filename or directory to push to the device.'})
    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.Pull,
        {
            'dest_file': 'Filename to write to on the host, if not specified, '
                         'prints the content to stdout.',
        })
    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.Reboot)
    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.RebootBootloader)
    common_cli.MakeSubparser(
        subparsers, parents, adb_commands.AdbCommands.Remount)
    common_cli.MakeSubparser(subparsers, parents, adb_commands.AdbCommands.Root)
    common_cli.MakeSubparser(subparsers, parents, adb_commands.AdbCommands.EnableVerity)
    common_cli.MakeSubparser(subparsers, parents, adb_commands.AdbCommands.DisableVerity)
    common_cli.MakeSubparser(subparsers, parents, Shell)

    if len(sys.argv) == 1:
        parser.print_help()
        return 2

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    if not args.rsa_key_path:
        default = os.path.expanduser('~/.android/adbkey')
        if os.path.isfile(default):
            args.rsa_key_path = [default]
    if args.rsa_key_path and not rsa_signer:
        parser.error('Please install either M2Crypto, python-rsa, or PycryptoDome')

    # Hacks so that the generated doc is nicer.
    if args.command_name == 'devices':
        return Devices(args)
    if args.command_name == 'help':
        parser.print_help()
        return 0
    if args.command_name == 'logcat':
        args.positional = args.options
    elif args.command_name == 'shell':
        args.positional = args.command

    return common_cli.StartCli(
        args,
        adb_commands.AdbCommands,
        auth_timeout_ms=int(args.auth_timeout_s * 1000),
        rsa_keys=[rsa_signer(path) for path in args.rsa_key_path])


if __name__ == '__main__':
    sys.exit(main())
