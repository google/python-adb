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

import io
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
    self.usb.ExpectWrite(b'download:%08x' % self._SumLengths(writes))

    if accept_data:
      self.usb.ExpectRead(b'DATA%08x' % self._SumLengths(writes))
    else:
      self.usb.ExpectRead(b'DATA%08x' % (self._SumLengths(writes) - 2))

    for data in writes:
      self.usb.ExpectWrite(data)

    if succeed:
      self.usb.ExpectRead(b'OKAYResult')
    else:
      self.usb.ExpectRead(b'FAILResult')

  def ExpectFlash(self, partition, succeed=True):
    self.usb.ExpectWrite(b'flash:%s' % partition)
    self.usb.ExpectRead(b'INFORandom info from the bootloader')
    if succeed:
      self.usb.ExpectRead(b'OKAYDone')
    else:
      self.usb.ExpectRead(b'FAILDone')

  def testDownload(self):
    raw = u'aoeuidhtnsqjkxbmwpyfgcrl'
    data = io.StringIO(raw)

    self.ExpectDownload([raw])
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)

    response = dev.Download(data)
    self.assertEqual(b'Result', response)

  def testDownloadFail(self):
    raw = u'aoeuidhtnsqjkxbmwpyfgcrl'
    data = io.StringIO(raw)

    self.ExpectDownload([raw], succeed=False)
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)
    with self.assertRaises(fastboot.FastbootRemoteFailure):
      dev.Download(data)

    data = io.StringIO(raw)
    self.ExpectDownload([raw], accept_data=False)
    with self.assertRaises(fastboot.FastbootTransferError):
      dev.Download(data)

  def testFlash(self):
    partition = b'yarr'

    self.ExpectFlash(partition)
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)

    output = io.BytesIO()
    def InfoCb(message):
      if message.header == b'INFO':
        output.write(message.message)
    response = dev.Flash(partition, info_cb=InfoCb)
    self.assertEqual(b'Done', response)
    self.assertEqual(b'Random info from the bootloader', output.getvalue())

  def testFlashFail(self):
    partition = b'matey'

    self.ExpectFlash(partition, succeed=False)
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)

    with self.assertRaises(fastboot.FastbootRemoteFailure):
      dev.Flash(partition)

  def testFlashFromFile(self):
    partition = b'somewhere'
    # More than one packet, ends somewhere into the 3rd packet.
    raw = b'SOMETHING' * 1086
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(raw)
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

    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)
    dev.FlashFromFile(
        partition, tmp.name, progress_callback=cb)
    self.assertEqual(len(pieces), len(progresses))
    os.remove(tmp.name)

  def testSimplerCommands(self):
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)

    self.usb.ExpectWrite(b'erase:vector')
    self.usb.ExpectRead(b'OKAY')
    dev.Erase('vector')

    self.usb.ExpectWrite(b'getvar:variable')
    self.usb.ExpectRead(b'OKAYstuff')
    self.assertEqual(b'stuff', dev.Getvar('variable'))

    self.usb.ExpectWrite(b'continue')
    self.usb.ExpectRead(b'OKAY')
    dev.Continue()

    self.usb.ExpectWrite(b'reboot')
    self.usb.ExpectRead(b'OKAY')
    dev.Reboot()

    self.usb.ExpectWrite(b'reboot-bootloader')
    self.usb.ExpectRead(b'OKAY')
    dev.RebootBootloader()

    self.usb.ExpectWrite(b'oem a little somethin')
    self.usb.ExpectRead(b'OKAYsomethin')
    self.assertEqual(b'somethin', dev.Oem('a little somethin'))

  def testVariousFailures(self):
    dev = fastboot.FastbootCommands()
    dev.ConnectDevice(handle=self.usb)

    self.usb.ExpectWrite(b'continue')
    self.usb.ExpectRead(b'BLEH')
    with self.assertRaises(fastboot.FastbootInvalidResponse):
      dev.Continue()

    self.usb.ExpectWrite(b'continue')
    self.usb.ExpectRead(b'DATA000000')
    with self.assertRaises(fastboot.FastbootStateMismatch):
      dev.Continue()


if __name__ == '__main__':
  unittest.main()
