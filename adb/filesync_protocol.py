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
"""ADB protocol implementation.

Implements the ADB protocol as seen in android's adb/adbd binaries, but only the
host side.
"""

import collections
import os
import stat
import struct
import time

import libusb1

from adb import adb_protocol
from adb import usb_exceptions

# Default mode for pushed files.
DEFAULT_PUSH_MODE = stat.S_IFREG | stat.S_IRWXU | stat.S_IRWXG
# Maximum size of a filesync DATA packet.
MAX_PUSH_DATA = 2 * 1024


class InvalidChecksumError(Exception):
    """Checksum of data didn't match expected checksum."""


class InterleavedDataError(Exception):
    """We only support command sent serially."""


class PushFailedError(Exception):
    """Pushing a file failed for some reason."""


DeviceFile = collections.namedtuple('DeviceFile', [
    'filename', 'mode', 'size', 'mtime'])


class FilesyncProtocol(object):
    """Implements the FileSync protocol as described in sync.txt."""

    @staticmethod
    def Stat(connection, filename):
        cnxn = FileSyncConnection(connection, b'<4I')
        cnxn.Send(b'STAT', filename)
        command, (mode, size, mtime) = cnxn.Read((b'STAT',), read_data=False)

        if command != b'STAT':
            raise adb_protocol.InvalidResponseError(
                'Expected STAT response to STAT, got %s' % command)
        return mode, size, mtime

    @classmethod
    def List(cls, connection, path):
        cnxn = FileSyncConnection(connection, b'<5I')
        cnxn.Send(b'LIST', path)
        files = []
        for cmd_id, header, filename in cnxn.ReadUntil((b'DENT',), b'DONE'):
            if cmd_id == b'DONE':
                break
            mode, size, mtime = header
            files.append(DeviceFile(filename, mode, size, mtime))
        return files

    @classmethod
    def Pull(cls, connection, filename, dest_file, progress_callback):
        """Pull a file from the device into the file-like dest_file."""
        if progress_callback:
            total_bytes = cls.Stat(connection, filename)[1]
            progress = cls._HandleProgress(lambda current: progress_callback(filename, current, total_bytes))
            next(progress)

        cnxn = FileSyncConnection(connection, b'<2I')
        cnxn.Send(b'RECV', filename)
        for cmd_id, _, data in cnxn.ReadUntil((b'DATA',), b'DONE'):
            if cmd_id == b'DONE':
                break
            dest_file.write(data)
            if progress_callback:
                progress.send(len(data))

    @classmethod
    def _HandleProgress(cls, progress_callback):
        """Calls the callback with the current progress and total bytes written/received.

        Args:
          progress_callback: callback method that accepts filename, bytes_written and total_bytes,
                     total_bytes will be -1 for file-like objects
        """
        current = 0
        while True:
            current += yield
            try:
                progress_callback(current)
            except Exception:  # pylint: disable=broad-except
                continue

    @classmethod
    def Push(cls, connection, datafile, filename,
             st_mode=DEFAULT_PUSH_MODE, mtime=0, progress_callback=None):
        """Push a file-like object to the device.

        Args:
          connection: ADB connection
          datafile: File-like object for reading from
          filename: Filename to push to
          st_mode: stat mode for filename
          mtime: modification time
          progress_callback: callback method that accepts filename, bytes_written and total_bytes

        Raises:
          PushFailedError: Raised on push failure.
        """

        fileinfo = ('{},{}'.format(filename, int(st_mode))).encode('utf-8')

        cnxn = FileSyncConnection(connection, b'<2I')
        cnxn.Send(b'SEND', fileinfo)

        if progress_callback:
            total_bytes = os.fstat(datafile.fileno()).st_size if isinstance(datafile, file) else -1
            progress = cls._HandleProgress(lambda current: progress_callback(filename, current, total_bytes))
            next(progress)

        while True:
            data = datafile.read(MAX_PUSH_DATA)
            if data:
                cnxn.Send(b'DATA', data)

                if progress_callback:
                    progress.send(len(data))
            else:
                break

        if mtime == 0:
            mtime = int(time.time())
        # DONE doesn't send data, but it hides the last bit of data in the size
        # field.
        cnxn.Send(b'DONE', size=mtime)
        for cmd_id, _, data in cnxn.ReadUntil((), b'OKAY', b'FAIL'):
            if cmd_id == b'OKAY':
                return
            raise PushFailedError(data)


class FileSyncConnection(object):
    """Encapsulate a FileSync service connection."""

    ids = [
        b'STAT', b'LIST', b'SEND', b'RECV', b'DENT', b'DONE', b'DATA', b'OKAY',
        b'FAIL', b'QUIT',
    ]
    id_to_wire, wire_to_id = adb_protocol.MakeWireIDs(ids)

    def __init__(self, adb_connection, recv_header_format):
        self.adb = adb_connection

        # Sending
        # Using a bytearray() saves a copy later when using libusb.
        self.send_buffer = bytearray(adb_protocol.MAX_ADB_DATA)
        self.send_idx = 0
        self.send_header_len = struct.calcsize(b'<2I')

        # Receiving
        self.recv_buffer = bytearray()
        self.recv_header_format = recv_header_format
        self.recv_header_len = struct.calcsize(recv_header_format)

    def Send(self, command_id, data=b'', size=0):
        """Send/buffer FileSync packets.

        Packets are buffered and only flushed when this connection is read from. All
        messages have a response from the device, so this will always get flushed.

        Args:
          command_id: Command to send.
          data: Optional data to send, must set data or size.
          size: Optionally override size from len(data).
        """
        if data:
            if not isinstance(data, bytes):
                data = data.encode('utf8')
            size = len(data)

        if not self._CanAddToSendBuffer(len(data)):
            self._Flush()
        buf = struct.pack(b'<2I', self.id_to_wire[command_id], size) + data
        self.send_buffer[self.send_idx:self.send_idx + len(buf)] = buf
        self.send_idx += len(buf)

    def Read(self, expected_ids, read_data=True):
        """Read ADB messages and return FileSync packets."""
        if self.send_idx:
            self._Flush()

        # Read one filesync packet off the recv buffer.
        header_data = self._ReadBuffered(self.recv_header_len)
        header = struct.unpack(self.recv_header_format, header_data)
        # Header is (ID, ...).
        command_id = self.wire_to_id[header[0]]

        if command_id not in expected_ids:
            if command_id == b'FAIL':
                reason = ''
                if self.recv_buffer:
                    reason = self.recv_buffer.decode('utf-8', errors='ignore')
                raise usb_exceptions.AdbCommandFailureException('Command failed: {}'.format(reason))
            raise adb_protocol.InvalidResponseError(
                'Expected one of %s, got %s' % (expected_ids, command_id))

        if not read_data:
            return command_id, header[1:]

        # Header is (ID, ..., size).
        size = header[-1]
        data = self._ReadBuffered(size)
        return command_id, header[1:-1], data

    def ReadUntil(self, expected_ids, *finish_ids):
        """Useful wrapper around Read."""
        while True:
            cmd_id, header, data = self.Read(expected_ids + finish_ids)
            yield cmd_id, header, data
            if cmd_id in finish_ids:
                break

    def _CanAddToSendBuffer(self, data_len):
        added_len = self.send_header_len + data_len
        return self.send_idx + added_len < adb_protocol.MAX_ADB_DATA

    def _Flush(self):
        try:
            self.adb.Write(self.send_buffer[:self.send_idx])
        except libusb1.USBError as e:
            raise adb_protocol.SendFailedError(
                'Could not send data %s' % self.send_buffer, e)
        self.send_idx = 0

    def _ReadBuffered(self, size):
        # Ensure recv buffer has enough data.
        while len(self.recv_buffer) < size:
            _, data = self.adb.ReadUntil(b'WRTE')
            self.recv_buffer += data

        result = self.recv_buffer[:size]
        self.recv_buffer = self.recv_buffer[size:]
        return result
