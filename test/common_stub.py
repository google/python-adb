"""Stubs for tests using common's usb handling."""

import binascii
import string

PRINTABLE_DATA = set(string.printable) - set(string.whitespace)


def _Dotify(data):
  return ''.join(char if char in PRINTABLE_DATA else '.' for char in data)


class StubUsb(object):
  """UsbHandle stub."""

  def __init__(self):
    self.written_data = []
    self.read_data = []
    self.timeout_ms = 0

  def BulkWrite(self, data, unused_timeout_ms=None):
    expected_data = self.written_data.pop(0)
    if expected_data != data:
      raise ValueError('Expected %s, got %s (%s)' % (
          _Dotify(expected_data), binascii.hexlify(data), _Dotify(data)))

  def BulkRead(self, length,
               timeout_ms=None):  # pylint: disable=unused-argument
    data = self.read_data.pop(0)
    if length < len(data):
      raise ValueError(
          'Overflow packet length. Read %d bytes, got %d bytes: %s',
          length, len(data))
    return data

  def ExpectWrite(self, data):
    self.written_data.append(data)

  def ExpectRead(self, data):
    self.read_data.append(data)

  def Timeout(self, timeout_ms):
    return timeout_ms if timeout_ms is not None else self.timeout_ms
