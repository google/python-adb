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
"""Tests for adb."""

import io
import struct
import unittest

from adb import adb_commands
from adb import adb_protocol
import common_stub


BANNER = 'blazetest'
LOCAL_ID = 1
REMOTE_ID = 2


class BaseAdbTest(unittest.TestCase):

  @classmethod
  def _ExpectWrite(cls, usb, command, arg0, arg1, data):
    usb.ExpectWrite(cls._MakeHeader(command, arg0, arg1, data))
    usb.ExpectWrite(data)
    if command == 'WRTE':
      cls._ExpectRead(usb, 'OKAY', 0, 0)

  @classmethod
  def _ExpectRead(cls, usb, command, arg0, arg1, data=''):
    usb.ExpectRead(cls._MakeHeader(command, arg0, arg1, data))
    if data:
      usb.ExpectRead(data)
    if command == 'WRTE':
      cls._ExpectWrite(usb, 'OKAY', LOCAL_ID, REMOTE_ID, '')

  @classmethod
  def _ConvertCommand(cls, command):
    return sum(ord(c) << (i * 8) for i, c in enumerate(command))

  @classmethod
  def _MakeHeader(cls, command, arg0, arg1, data):
    command = cls._ConvertCommand(command)
    magic = command ^ 0xFFFFFFFF
    checksum = adb_protocol.AdbMessage.CalculateChecksum(data)
    return struct.pack('<6I', command, arg0, arg1, len(data), checksum, magic)

  @classmethod
  def _ExpectConnection(cls, usb):
    cls._ExpectWrite(usb, 'CNXN', 0x01000000, 4096, 'host::%s\0' % BANNER)
    cls._ExpectRead(usb, 'CNXN', 0, 0, 'device::\0')

  @classmethod
  def _ExpectOpen(cls, usb, service):
    cls._ExpectWrite(usb, 'OPEN', LOCAL_ID, 0, service)
    cls._ExpectRead(usb, 'OKAY', REMOTE_ID, LOCAL_ID)

  @classmethod
  def _ExpectClose(cls, usb):
    cls._ExpectRead(usb, 'CLSE', REMOTE_ID, 0)
    cls._ExpectWrite(usb, 'CLSE', LOCAL_ID, REMOTE_ID, '')

  @classmethod
  def _Connect(cls, usb):
    return adb_commands.AdbCommands.Connect(usb, BANNER)


class AdbTest(BaseAdbTest):

  @classmethod
  def _ExpectCommand(cls, service, command, *responses):
    usb = common_stub.StubUsb()
    cls._ExpectConnection(usb)
    cls._ExpectOpen(usb, '%s:%s\0' % (service, command))

    for response in responses:
      cls._ExpectRead(usb, 'WRTE', REMOTE_ID, 0, response)
    cls._ExpectClose(usb)
    return usb

  def testConnect(self):
    usb = common_stub.StubUsb()
    self._ExpectConnection(usb)

    adb_commands.AdbCommands.Connect(usb, BANNER)

  def testSmallResponseShell(self):
    command = 'keepin it real'
    response = 'word.'
    usb = self._ExpectCommand('shell', command, response)

    adb_commands = self._Connect(usb)
    self.assertEqual(response, adb_commands.Shell(command))

  def testBigResponseShell(self):
    command = 'keepin it real big'
    # The data doesn't have to be big, the point is that it just concatenates
    # the data from different WRTEs together.
    responses = ['other stuff, ', 'and some words.']

    usb = self._ExpectCommand('shell', command, *responses)

    adb_commands = self._Connect(usb)
    self.assertEqual(''.join(responses), adb_commands.Shell(command))

  def testStreamingResponseShell(self):
    command = 'keepin it real big'
    # expect multiple lines

    responses = ['other stuff, ', 'and some words.']

    usb = self._ExpectCommand('shell', command, *responses)

    adb_commands = self._Connect(usb)
    response_count = 0
    for (expected,actual) in zip(responses, adb_commands.StreamingShell(command)):
      self.assertEqual(expected, actual)
      response_count = response_count + 1
    self.assertEqual(len(responses), response_count)

  def testReboot(self):
    usb = self._ExpectCommand('reboot', '', '')
    adb_commands = self._Connect(usb)
    adb_commands.Reboot()

  def testRebootBootloader(self):
    usb = self._ExpectCommand('reboot', 'bootloader', '')
    adb_commands = self._Connect(usb)
    adb_commands.RebootBootloader()

  def testRemount(self):
    usb = self._ExpectCommand('remount', '', '')
    adb_commands = self._Connect(usb)
    adb_commands.Remount()

  def testRoot(self):
    usb = self._ExpectCommand('root', '', '')
    adb_commands = self._Connect(usb)
    adb_commands.Root()


class FilesyncAdbTest(BaseAdbTest):

  @classmethod
  def _MakeSyncHeader(cls, command, *int_parts):
    command = cls._ConvertCommand(command)
    return struct.pack('<%dI' % (len(int_parts) + 1), command, *int_parts)

  @classmethod
  def _MakeWriteSyncPacket(cls, command, data='', size=None):
    return cls._MakeSyncHeader(command, size or len(data)) + data.encode("ascii")

  @classmethod
  def _ExpectSyncCommand(cls, write_commands, read_commands):
    usb = common_stub.StubUsb()
    cls._ExpectConnection(usb)
    cls._ExpectOpen(usb, 'sync:\0')

    while write_commands or read_commands:
      if write_commands:
        command = write_commands.pop(0)
        cls._ExpectWrite(usb, 'WRTE', LOCAL_ID, REMOTE_ID, command)

      if read_commands:
        command = read_commands.pop(0)
        cls._ExpectRead(usb, 'WRTE', REMOTE_ID, LOCAL_ID, command)

    cls._ExpectClose(usb)
    return usb

  def testPush(self):
    filedata = u'alo there, govnah'
    mtime = 100

    send = [
        self._MakeWriteSyncPacket('SEND', '/data,33272'),
        self._MakeWriteSyncPacket('DATA', filedata),
        self._MakeWriteSyncPacket('DONE', size=mtime),
    ]
    data = 'OKAY\0\0\0\0'
    usb = self._ExpectSyncCommand([b''.join(send)], [data])

    adb_commands = self._Connect(usb)
    adb_commands.Push(io.StringIO(filedata), '/data', mtime=mtime)

  def testPull(self):
    filedata = "g'ddayta, govnah"

    recv = self._MakeWriteSyncPacket('RECV', '/data')
    data = [
        self._MakeWriteSyncPacket('DATA', filedata),
        self._MakeWriteSyncPacket('DONE'),
    ]
    usb = self._ExpectSyncCommand([recv], [b''.join(data)])
    adb_commands = self._Connect(usb)
    self.assertEqual(filedata, adb_commands.Pull('/data'))

if __name__ == '__main__':
  unittest.main()
