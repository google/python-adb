"""Stubs for tests using common's usb handling."""

import binascii
import signal
import string
import sys
import time
from mock import mock

from adb.common import TcpHandle, UsbHandle
from adb.usb_exceptions import TcpTimeoutException

PRINTABLE_DATA = set(string.printable) - set(string.whitespace)


def _Dotify(data):
  if sys.version_info.major == 3:
    data = (chr(char) for char in data)
  return ''.join(char if char in PRINTABLE_DATA else '.' for char in data)


class StubHandleBase(object):
  def __init__(self, timeout_ms, is_tcp=False):
    self.written_data = []
    self.read_data = []
    self.is_tcp = is_tcp
    self.timeout_ms = timeout_ms

  def _signal_handler(self, signum, frame):
      raise TcpTimeoutException('End of time')

  def _return_seconds(self, time_ms):
      return (float(time_ms)/1000) if time_ms else 0

  def _alarm_sounder(self, timeout_ms):
    signal.signal(signal.SIGALRM, self._signal_handler)
    signal.setitimer(signal.ITIMER_REAL,
            self._return_seconds(timeout_ms))

  def ExpectWrite(self, data):
    if not isinstance(data, bytes):
      data = data.encode('utf8')
    self.written_data.append(data)

  def ExpectRead(self, data):
    if not isinstance(data, bytes):
      data = data.encode('utf8')
    self.read_data.append(data)

  def BulkWrite(self, data, timeout_ms=None):
    expected_data = self.written_data.pop(0)
    if isinstance(data, bytearray):
      data = bytes(data)
    if not isinstance(data, bytes):
      data = data.encode('utf8')
    if expected_data != data:
      raise ValueError('Expected %s (%s) got %s (%s)' % (
          binascii.hexlify(expected_data), _Dotify(expected_data),
          binascii.hexlify(data), _Dotify(data)))
    if self.is_tcp and b'i_need_a_timeout' in data:
      self._alarm_sounder(timeout_ms)
      time.sleep(2*self._return_seconds(timeout_ms))

  def BulkRead(self, length,
               timeout_ms=None):  # pylint: disable=unused-argument
    data = self.read_data.pop(0)
    if length < len(data):
      raise ValueError(
          'Overflow packet length. Read %d bytes, got %d bytes: %s',
          length, len(data))
    if self.is_tcp and b'i_need_a_timeout' in data:
      self._alarm_sounder(timeout_ms)
      time.sleep(2*self._return_seconds(timeout_ms))
    return bytearray(data)

  def Timeout(self, timeout_ms):
    return timeout_ms if timeout_ms is not None else self.timeout_ms


class StubUsb(UsbHandle):
  """UsbHandle stub."""
  def __init__(self, device, setting, usb_info=None, timeout_ms=None):
    super(StubUsb, self).__init__(device, setting, usb_info, timeout_ms)
    self.stub_base = StubHandleBase(0)

  def ExpectWrite(self, data):
    return self.stub_base.ExpectWrite(data)

  def ExpectRead(self, data):
    return self.stub_base.ExpectRead(data)

  def BulkWrite(self, data, unused_timeout_ms=None):
    return self.stub_base.BulkWrite(data, unused_timeout_ms)

  def BulkRead(self, length, timeout_ms=None):
    return self.stub_base.BulkRead(length, timeout_ms)

  def Timeout(self, timeout_ms):
    return self.stub_base.Timeout(timeout_ms)


class StubTcp(TcpHandle):
  def __init__(self, serial, timeout_ms=None):
    """TcpHandle stub."""
    self._connect = mock.MagicMock(return_value=None)

    super(StubTcp, self).__init__(serial, timeout_ms)
    self.stub_base = StubHandleBase(0, is_tcp=True)

  def ExpectWrite(self, data):
    return self.stub_base.ExpectWrite(data)

  def ExpectRead(self, data):
    return self.stub_base.ExpectRead(data)

  def BulkWrite(self, data, unused_timeout_ms=None):
    return self.stub_base.BulkWrite(data, unused_timeout_ms)

  def BulkRead(self, length, timeout_ms=None):
    return self.stub_base.BulkRead(length, timeout_ms)

  def Timeout(self, timeout_ms):
    return self.stub_base.Timeout(timeout_ms)
