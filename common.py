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
"""Common code for ADB and Fastboot.

Common usb browsing, and usb communication.
"""
import logging
import threading
import weakref

import libusb1
import usb1

import usb_exceptions

DEFAULT_TIMEOUT_MS = 100

SYSFS_USB_BASE_PATH = '/sys/bus/usb/devices/'

_LOG = logging.getLogger('android_usb')


class UsbHandle(object):
  """USB communication object. Not thread-safe.

  Handles reading and writing over USB with the proper endpoints, exceptions,
  and interface claiming.

  Important methods:
    FlushBuffers()
    BulkRead(int length)
    BulkWrite(bytes data)
  """

  _HANDLE_CACHE = weakref.WeakValueDictionary()
  _HANDLE_CACHE_LOCK = threading.Lock()

  def __init__(self, device, setting, usb_info=None, timeout_ms=None):
    """Initialize USB Handle.

    Arguments:
      device: libusb_device to connect to.
      setting: libusb setting with the correct endpoints to communicate with.
      usb_info: String describing the usb path/serial/device, for debugging.
      timeout_ms: Timeout in milliseconds for all I/O.
    """
    self._setting = setting
    self._device = device
    self._handle = None

    self._usb_info = usb_info or ''
    self._timeout_ms = timeout_ms or DEFAULT_TIMEOUT_MS

  @property
  def usb_info(self):
    try:
      sn = self.serial_number
    except libusb1.USBError:
      sn = ''
    if sn and sn != self._usb_info:
      return '%s %s' % (self._usb_info, sn)
    return self._usb_info

  def Open(self):
    """Opens the USB device for this setting, and claims the interface."""
    # Make sure we close any previous handle open to this usb device.
    port_path = tuple(self.port_path)
    with self._HANDLE_CACHE_LOCK:
      old_handle = self._HANDLE_CACHE.get(port_path)
      if old_handle is not None:
        old_handle.Close()

    self._read_endpoint = None
    self._write_endpoint = None

    for endpoint in self._setting.iterEndpoints():
      address = endpoint.getAddress()
      if address & libusb1.USB_ENDPOINT_DIR_MASK:
        self._read_endpoint = address
        self._max_read_packet_len = endpoint.getMaxPacketSize()
      else:
        self._write_endpoint = address

    assert self._read_endpoint is not None
    assert self._write_endpoint is not None

    handle = self._device.open()
    iface_number = self._setting.getNumber()
    try:
      if handle.kernelDriverActive(iface_number):
        handle.detachKernelDriver(iface_number)
    except libusb1.USBError as e:
      if e.value == libusb1.LIBUSB_ERROR_NOT_FOUND:
        _LOG.warning('Kernel driver not found for interface: %s.', iface_number)
      else:
        raise
    handle.claimInterface(iface_number)
    self._handle = handle
    self._interface_number = iface_number

    with self._HANDLE_CACHE_LOCK:
      self._HANDLE_CACHE[port_path] = self
    # When this object is deleted, make sure it's closed.
    weakref.ref(self, self.Close)

  @property
  def serial_number(self):
    return self._device.getSerialNumber()

  @property
  def port_path(self):
    return [self._device.getBusNumber()] + self._device.getPortNumberList()

  def Close(self):
    if self._handle is None:
      return
    try:
      self._handle.releaseInterface(self._interface_number)
      self._handle.close()
    except libusb1.USBError:
      _LOG.info('USBError while closing handle %s: ',
                self.usb_info, exc_info=True)
    finally:
      self._handle = None

  def Timeout(self, timeout_ms):
    return timeout_ms if timeout_ms is not None else self._timeout_ms

  def FlushBuffers(self):
    while True:
      try:
        self.BulkRead(self._max_read_packet_len, timeout_ms=10)
      except usb_exceptions.ReadFailedError as e:
        if e.usb_error.value == libusb1.LIBUSB_ERROR_TIMEOUT:
          break
        raise

  def BulkWrite(self, data, timeout_ms=None):
    if self._handle is None:
      raise usb_exceptions.WriteFailedError(
          'This handle has been closed, probably due to another being opened.',
          None)
    try:
      return self._handle.bulkWrite(
          self._write_endpoint, data, timeout=self.Timeout(timeout_ms))
    except libusb1.USBError as e:
      raise usb_exceptions.WriteFailedError(
          'Could not send data to %s (timeout %sms)' % (
              self.usb_info, self.Timeout(timeout_ms)), e)

  def BulkRead(self, length, timeout_ms=None):
    if self._handle is None:
      raise usb_exceptions.ReadFailedError(
          'This handle has been closed, probably due to another being opened.',
          None)
    try:
      return self._handle.bulkRead(
          self._read_endpoint, length, timeout=self.Timeout(timeout_ms))
    except libusb1.USBError as e:
      raise usb_exceptions.ReadFailedError(
          'Could not receive data from %s (timeout %sms)' % (
              self.usb_info, self.Timeout(timeout_ms)), e)

  @classmethod
  def FromPath(cls, port_path, filter_callback, timeout_ms=None):
    """Find and return device on the given path.

    Args:
      port_path: USB port path (list of numbers)
      filter_callback: Function that takes a device and returns if it matches
          and which setting to use.
      timeout_ms: Default timeout of commands in milliseconds.

    Returns:
      An instance of UsbHandle.

    Raises:
      DeviceNotFoundError: Raised if the device is not available.
      InvalidConfigurationError: Device on port does not have a matching
          configuration.
    """
    devices = cls.GetDevices(filter_callback, timeout_ms=timeout_ms)
    for device in devices:
      if device.port_path == port_path:
        device.Open()
        device.FlushBuffers()
        return device

    raise usb_exceptions.DeviceNotFoundError(
        'No device on part %s.' % port_path)

  @classmethod
  def FromSerial(cls, serial, filter_callback, timeout_ms=None):
    """Find and return device with the given serial.

    Args:
      serial: Android Serial eg GLASS12345678
      filter_callback: Function that takes a device and returns if it matches
          and which setting to use.
      timeout_ms: Default timeout of commands in milliseconds.

    Returns:
      An instance of UsbHandle.

    Raises:
      DeviceNotFoundError: Raised if the device is not available.
      InvalidConfigurationError: Device on port does not have a matching
          configuration.
    """
    def GetDevice():
      ctx = usb1.USBContext()
      for device in ctx.getDeviceList(skip_on_error=True):
        setting = filter_callback(device)
        if setting is None:
          continue

        if device.getSerialNumber() == serial:
          return device

    return cls._FromCallback(filter_callback, GetDevice, serial,
                             timeout_ms=timeout_ms)

  @classmethod
  def FromFirst(cls, filter_callback, timeout_ms=None):
    """Find and return the first device available.

    Args:
      filter_callback: Function that takes a device and returns if it matches
          and which setting to use.
      timeout_ms: Default timeout of commands in milliseconds.

    Returns:
      An instance of UsbHandle.

    Raises:
      DeviceNotFoundError: Raised if the device is not available.
      InvalidConfigurationError: Device on port does not have a matching
          configuration.
    """
    devices = cls.GetDevices(filter_callback, timeout_ms=timeout_ms)
    try:
      usb = next(devices)
    except StopIteration:
      raise usb_exceptions.DeviceNotFoundError('No device available.')
    usb.Open()
    usb.FlushBuffers()
    return usb

  @classmethod
  def GetDevices(cls, filter_callback, timeout_ms=None):
    """A generator of UsbHandle for devices available.

    Args:
      filter_callback: Function that takes a device and returns if it matches
          and which setting to use.
      timeout_ms: Default timeout of commands in milliseconds.

    Yields:
      A UsbHandle instance.
    """
    ctx = usb1.USBContext()
    for device in ctx.getDeviceList(skip_on_error=True):
      setting = filter_callback(device)
      if setting is None:
        continue

      yield cls(device, setting, timeout_ms=timeout_ms)

  @classmethod
  def _FromCallback(cls, filter_callback, usb_callback, usb_info,
                    timeout_ms=None):
    """Find and return device returned by usb_callback.

    Args:
      filter_callback: Function that takes a device and returns if it matches
          and which setting to use.
      usb_callback: Callback that returns a single usb device
      usb_info: Info string in case device cannot be found.
      timeout_ms: Default timeout of commands in milliseconds.

    Returns:
      An instance of UsbHandle.

    Raises:
      DeviceNotFoundError: Raised if the device is not available.
      InvalidConfigurationError: Device on port does not have a matching
          configuration.
    """
    for _ in xrange(3):
      device = usb_callback()
      if device:
        break
    else:
      raise usb_exceptions.DeviceNotFoundError(
          'Device %s not found after 3 retries.' % usb_info)

    setting = filter_callback(device)
    if setting is None:
      raise usb_exceptions.InvalidConfigurationError(
          "Device on port %s isn't in the expected configuration", usb_info)

    usb = cls(device, setting, usb_info=usb_info, timeout_ms=timeout_ms)
    usb.Open()
    usb.FlushBuffers()
    return usb
