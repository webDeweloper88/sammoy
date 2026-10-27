"""PN532 HSU for Linux UART, bounded frames and explicit wake-up.

Same public target metadata as LinuxI2cPn532; no wallet/card-memory operations.
"""
import fcntl
import math
import os
import select
import termios
import time

ACK = bytes.fromhex('0000ff00ff00')
NAK = bytes.fromhex('0000ffff0000')
WAKE = b'\x55\x55' + b'\0' * 12
MAX_FRAME = 262


def encode(command):
    data = b'\xd4' + bytes(command)
    if not 2 <= len(data) <= 254:
        raise ValueError('Invalid PN532 command size')
    return b'\0\0\xff' + bytes([len(data), -len(data) & 255]) + data + bytes([-sum(data) & 255, 0])


def extract(buffer):
    """Consume one complete frame; retain partial data. Reject invalid framing."""
    start = buffer.find(b'\0\0\xff')
    if start < 0:
        if len(buffer) > MAX_FRAME:
            raise RuntimeError('PN532 frame overflow')
        return None
    if start:
        del buffer[:start]
    if len(buffer) < 6:
        return None
    if buffer[:6] in (ACK, NAK):
        value = bytes(buffer[:6]); del buffer[:6]
        return ('ack' if value == ACK else 'nak', b'')
    length, check = buffer[3:5]
    if not 1 <= length <= 254 or (length + check) & 255:
        raise RuntimeError('PN532 invalid frame length')
    total = length + 7
    if len(buffer) < total:
        return None
    data = bytes(buffer[5:5+length])
    if (sum(data) + buffer[5+length]) & 255 or buffer[6+length] != 0:
        raise RuntimeError('PN532 invalid checksum/postamble')
    del buffer[:total]
    return ('data', data)


def target_info(response):
    if not response:
        raise RuntimeError('PN532 empty target response')
    if response[0] == 0:
        if len(response) != 1:
            raise RuntimeError('PN532 invalid empty target response')
        return None
    if response[0] != 1 or len(response) < 6:
        raise RuntimeError('PN532 invalid target response')
    length = response[5]
    if length not in (4, 7, 10) or len(response) < 6 + length:
        raise RuntimeError('PN532 invalid UID length')
    return {'uid': bytes(response[6:6+length]), 'sak': response[4],
            'atqa': bytes(response[2:4]).hex().upper()}


class LinuxHsuPn532:
    def __init__(self, device='/dev/ttyS9', baud_rate=115200):
        if baud_rate != 115200:
            raise ValueError('PN532 HSU profile requires 115200 baud')
        self.fd = None
        self.original = None
        self.wake_pending = True
        self.buffer = bytearray()
        fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.fd = fd
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL)
            self.original = termios.tcgetattr(fd)
            conf = termios.tcgetattr(fd)
            conf[0] = conf[1] = conf[3] = 0
            conf[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            conf[4] = conf[5] = termios.B115200
            conf[6][termios.VMIN] = conf[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, conf)
            termios.tcflush(fd, termios.TCIFLUSH)
        except BaseException:
            self.close()
            raise

    def close(self):
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                if self.original is not None:
                    termios.tcsetattr(fd, termios.TCSANOW, self.original)
            finally:
                try:
                    fcntl.ioctl(fd, termios.TIOCNXCL)
                finally:
                    os.close(fd)

    def _write(self, data, deadline):
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError('PN532 write timed out')
            try:
                count = os.write(self.fd, data)
            except BlockingIOError:
                continue
            if not count:
                raise OSError('PN532 UART closed during write')
            data = data[count:]

    def _command(self, command, timeout=1.0):
        if self.fd is None:
            raise OSError('PN532 UART is closed')
        if not math.isfinite(timeout) or not 0 < timeout <= 5:
            raise ValueError('PN532 timeout out of range')
        deadline = time.monotonic() + timeout
        self.buffer.clear()
        termios.tcflush(self.fd, termios.TCIFLUSH)
        data = encode(command)
        if self.wake_pending:
            data = WAKE + data
        self._write(data, deadline)
        acknowledged = False
        while True:
            result = extract(self.buffer)
            if result:
                kind, payload = result
                if kind == 'nak':
                    raise RuntimeError('PN532 NAK')
                if kind == 'ack':
                    acknowledged = True
                    continue
                if not acknowledged or payload[:2] != bytes([0xd5, (command[0]+1) & 255]):
                    raise RuntimeError('PN532 unexpected response')
                self.wake_pending = False
                return payload[2:]
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                # Cancel outstanding polling; caller reconnects before next command.
                try:
                    self._write(ACK, time.monotonic()+0.1)
                except (OSError, TimeoutError):
                    pass
                raise TimeoutError('PN532 response timed out')
            try:
                chunk = os.read(self.fd, MAX_FRAME)
            except BlockingIOError:
                continue
            if not chunk:
                raise OSError('PN532 UART disconnected')
            self.buffer.extend(chunk)
            if len(self.buffer) > MAX_FRAME + len(ACK):
                raise RuntimeError('PN532 response overflow')

    @property
    def firmware_version(self):
        result = self._command(b'\x02')
        if len(result) != 4 or result[0] != 0x32:
            raise RuntimeError('Not a supported PN532')
        return tuple(result)

    def SAM_configuration(self):
        if self._command(bytes.fromhex('14011401')) != b'':
            raise RuntimeError('PN532 invalid SAM response')
        # Finite passive retries return target count0 when no card is present.
        if self._command(bytes.fromhex('320501ff01')) != b'':
            raise RuntimeError('PN532 invalid RF configuration response')

    def read_target_info(self, timeout=1.0):
        return target_info(self._command(bytes.fromhex('4a0100'), timeout=max(0.25, timeout)))
