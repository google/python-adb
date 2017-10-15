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


BANNER = b'blazetest'
LOCAL_ID = 1
REMOTE_ID = 2


class BaseAdbTest(unittest.TestCase):

  @classmethod
  def _ExpectWrite(cls, usb, command, arg0, arg1, data):
    usb.ExpectWrite(cls._MakeHeader(command, arg0, arg1, data))
    usb.ExpectWrite(data)
    if command == b'WRTE':
      cls._ExpectRead(usb, b'OKAY', 0, 0)

  @classmethod
  def _ExpectRead(cls, usb, command, arg0, arg1, data=b''):
    usb.ExpectRead(cls._MakeHeader(command, arg0, arg1, data))
    if data:
      usb.ExpectRead(data)
    if command == b'WRTE':
      cls._ExpectWrite(usb, b'OKAY', LOCAL_ID, REMOTE_ID, b'')

  @classmethod
  def _ConvertCommand(cls, command):
    return sum(c << (i * 8) for i, c in enumerate(bytearray(command)))

  @classmethod
  def _MakeHeader(cls, command, arg0, arg1, data):
    command = cls._ConvertCommand(command)
    magic = command ^ 0xFFFFFFFF
    checksum = adb_protocol.AdbMessage.CalculateChecksum(data)
    return struct.pack(b'<6I', command, arg0, arg1, len(data), checksum, magic)

  @classmethod
  def _ExpectConnection(cls, usb):
    cls._ExpectWrite(usb, b'CNXN', 0x01000000, 4096, b'host::%s\0' % BANNER)
    cls._ExpectRead(usb, b'CNXN', 0, 0, b'device::\0')

  @classmethod
  def _ExpectOpen(cls, usb, service):
    cls._ExpectWrite(usb, b'OPEN', LOCAL_ID, 0, service)
    cls._ExpectRead(usb, b'OKAY', REMOTE_ID, LOCAL_ID)

  @classmethod
  def _ExpectClose(cls, usb):
    cls._ExpectRead(usb, b'CLSE', REMOTE_ID, 0)
    cls._ExpectWrite(usb, b'CLSE', LOCAL_ID, REMOTE_ID, b'')

  @classmethod
  def _Connect(cls, usb):
    return adb_commands.AdbCommands.Connect(usb, BANNER)


class AdbTest(BaseAdbTest):

  @classmethod
  def _ExpectCommand(cls, service, command, *responses):
    usb = common_stub.StubUsb()
    cls._ExpectConnection(usb)
    cls._ExpectOpen(usb, b'%s:%s\0' % (service, command))

    for response in responses:
      cls._ExpectRead(usb, b'WRTE', REMOTE_ID, 0, response)
    cls._ExpectClose(usb)
    return usb

  def testConnect(self):
    usb = common_stub.StubUsb()
    self._ExpectConnection(usb)

    adb_commands.AdbCommands.Connect(usb, BANNER)

  def testSmallResponseShell(self):
    command = b'keepin it real'
    response = 'word.'
    usb = self._ExpectCommand(b'shell', command, response)

    adb_commands = self._Connect(usb)
    self.assertEqual(response, adb_commands.Shell(command))

  def testBigResponseShell(self):
    command = b'keepin it real big'
    # The data doesn't have to be big, the point is that it just concatenates
    # the data from different WRTEs together.
    responses = [b'other stuff, ', b'and some words.']

    usb = self._ExpectCommand(b'shell', command, *responses)

    adb_commands = self._Connect(usb)
    self.assertEqual(b''.join(responses).decode('utf8'),
                     adb_commands.Shell(command))

  def testStreamingResponseShell(self):
    command = b'keepin it real big'
    # expect multiple lines

    responses = ['other stuff, ', 'and some words.']

    usb = self._ExpectCommand(b'shell', command, *responses)

    adb_commands = self._Connect(usb)
    response_count = 0
    for (expected,actual) in zip(responses, adb_commands.StreamingShell(command)):
      self.assertEqual(expected, actual)
      response_count = response_count + 1
    self.assertEqual(len(responses), response_count)

  def testReboot(self):
    usb = self._ExpectCommand(b'reboot', b'', b'')
    adb_commands = self._Connect(usb)
    adb_commands.Reboot()

  def testRebootBootloader(self):
    usb = self._ExpectCommand(b'reboot', b'bootloader', b'')
    adb_commands = self._Connect(usb)
    adb_commands.RebootBootloader()

  def testRemount(self):
    usb = self._ExpectCommand(b'remount', b'', b'')
    adb_commands = self._Connect(usb)
    adb_commands.Remount()

  def testRoot(self):
    usb = self._ExpectCommand(b'root', b'', b'')
    adb_commands = self._Connect(usb)
    adb_commands.Root()


class FilesyncAdbTest(BaseAdbTest):

  @classmethod
  def _MakeSyncHeader(cls, command, *int_parts):
    command = cls._ConvertCommand(command)
    return struct.pack(b'<%dI' % (len(int_parts) + 1), command, *int_parts)

  @classmethod
  def _MakeWriteSyncPacket(cls, command, data=b'', size=None):
    if not isinstance(data, bytes):
      data = data.encode('utf8')
    return cls._MakeSyncHeader(command, size or len(data)) + data

  @classmethod
  def _ExpectSyncCommand(cls, write_commands, read_commands):
    usb = common_stub.StubUsb()
    cls._ExpectConnection(usb)
    cls._ExpectOpen(usb, b'sync:\0')

    while write_commands or read_commands:
      if write_commands:
        command = write_commands.pop(0)
        cls._ExpectWrite(usb, b'WRTE', LOCAL_ID, REMOTE_ID, command)

      if read_commands:
        command = read_commands.pop(0)
        cls._ExpectRead(usb, b'WRTE', REMOTE_ID, LOCAL_ID, command)

    cls._ExpectClose(usb)
    return usb

  def testPush(self):
    filedata = u'alo there, govnah'
    mtime = 100

    send = [
        self._MakeWriteSyncPacket(b'SEND', b'/data,33272'),
        self._MakeWriteSyncPacket(b'DATA', filedata),
        self._MakeWriteSyncPacket(b'DONE', size=mtime),
    ]
    data = b'OKAY\0\0\0\0'
    usb = self._ExpectSyncCommand([b''.join(send)], [data])

    adb_commands = self._Connect(usb)
    adb_commands.Push(io.StringIO(filedata), '/data', mtime=mtime)

  def testPull(self):
    filedata = b"g'ddayta, govnah"

    recv = self._MakeWriteSyncPacket(b'RECV', b'/data')
    data = [
        self._MakeWriteSyncPacket(b'DATA', filedata),
        self._MakeWriteSyncPacket(b'DONE'),
    ]
    usb = self._ExpectSyncCommand([recv], [b''.join(data)])
    adb_commands = self._Connect(usb)
    self.assertEqual(filedata, adb_commands.Pull('/data'))

if __name__ == '__main__':
  unittest.main()
