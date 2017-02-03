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
"""Tests for adb.fastboot."""

import sys
PYTHON_27 = sys.version_info < (3,0)

if PYTHON_27:
    from cStringIO import StringIO
else:
    from io import StringIO
import os
import tempfile
import unittest

import common_stub
from adb import fastboot


class FastbootTest(unittest.TestCase):

  def setUp(self):
    self.usb = common_stub.StubUsb()

  @staticmethod
  def _SumLengths(items):
    return sum(len(item) for item in items)

  def ExpectDownload(self, writes, succeed=True, accept_data=True):
    self.usb.ExpectWrite('download:%08x' % self._SumLengths(writes))

    if accept_data:
      self.usb.ExpectRead('DATA%08x' % self._SumLengths(writes))
    else:
      self.usb.ExpectRead('DATA%08x' % (self._SumLengths(writes) - 2))

    for data in writes:
      self.usb.ExpectWrite(data)

    if succeed:
      self.usb.ExpectRead('OKAYResult')
    else:
      self.usb.ExpectRead('FAILResult')

  def ExpectFlash(self, partition, succeed=True):
    self.usb.ExpectWrite('flash:%s' % partition)
    self.usb.ExpectRead('INFORandom info from the bootloader')
    if succeed:
      self.usb.ExpectRead('OKAYDone')
    else:
      self.usb.ExpectRead('FAILDone')

  def testDownload(self):
    raw = 'aoeuidhtnsqjkxbmwpyfgcrl'
    data = StringIO(raw)

    self.ExpectDownload([raw])
    commands = fastboot.FastbootCommands(self.usb)

    response = commands.Download(data)
    self.assertEqual('Result', response)

  def testDownloadFail(self):
    raw = 'aoeuidhtnsqjkxbmwpyfgcrl'
    data = StringIO(raw)

    self.ExpectDownload([raw], succeed=False)
    commands = fastboot.FastbootCommands(self.usb)
    with self.assertRaises(fastboot.FastbootRemoteFailure):
      commands.Download(data)

    data = StringIO(raw)
    self.ExpectDownload([raw], accept_data=False)
    with self.assertRaises(fastboot.FastbootTransferError):
      commands.Download(data)

  def testFlash(self):
    partition = 'yarr'

    self.ExpectFlash(partition)
    commands = fastboot.FastbootCommands(self.usb)

    output = StringIO()
    def InfoCb(message):
      if message.header == 'INFO':
        output.write(message.message)
    response = commands.Flash(partition, info_cb=InfoCb)
    self.assertEqual('Done', response)
    self.assertEqual('Random info from the bootloader', output.getvalue())

  def testFlashFail(self):
    partition = 'matey'

    self.ExpectFlash(partition, succeed=False)
    commands = fastboot.FastbootCommands(self.usb)

    with self.assertRaises(fastboot.FastbootRemoteFailure):
      commands.Flash(partition)

  def testFlashFromFile(self):
    partition = 'somewhere'
    # More than one packet, ends somewhere into the 3rd packet.
    raw = 'SOMETHING' * 1086
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(raw.encode('ascii'))
    tmp.close()
    progresses = []

    pieces = []
    chunk_size = fastboot.FastbootProtocol(None).chunk_kb * 1024
    while raw:
      pieces.append(raw[:chunk_size])
      raw = raw[chunk_size:]
    self.ExpectDownload(pieces)
    self.ExpectFlash(partition)

    cb = lambda progress, total: progresses.append((progress, total))

    commands = fastboot.FastbootCommands(self.usb)
    commands.FlashFromFile(
        partition, tmp.name, progress_callback=cb)
    self.assertEqual(len(pieces), len(progresses))
    os.remove(tmp.name)

  def testSimplerCommands(self):
    commands = fastboot.FastbootCommands(self.usb)

    self.usb.ExpectWrite('erase:vector')
    self.usb.ExpectRead('OKAY')
    commands.Erase('vector')

    self.usb.ExpectWrite('getvar:variable')
    self.usb.ExpectRead('OKAYstuff')
    self.assertEqual('stuff', commands.Getvar('variable'))

    self.usb.ExpectWrite('continue')
    self.usb.ExpectRead('OKAY')
    commands.Continue()

    self.usb.ExpectWrite('reboot')
    self.usb.ExpectRead('OKAY')
    commands.Reboot()

    self.usb.ExpectWrite('reboot-bootloader')
    self.usb.ExpectRead('OKAY')
    commands.RebootBootloader()

    self.usb.ExpectWrite('oem a little somethin')
    self.usb.ExpectRead('OKAYsomethin')
    self.assertEqual('somethin', commands.Oem('a little somethin'))

  def testVariousFailures(self):
    commands = fastboot.FastbootCommands(self.usb)

    self.usb.ExpectWrite('continue')
    self.usb.ExpectRead('BLEH')
    with self.assertRaises(fastboot.FastbootInvalidResponse):
      commands.Continue()

    self.usb.ExpectWrite('continue')
    self.usb.ExpectRead('DATA000000')
    with self.assertRaises(fastboot.FastbootStateMismatch):
      commands.Continue()


if __name__ == '__main__':
  unittest.main()
