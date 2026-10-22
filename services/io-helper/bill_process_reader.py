"""Isolated GPIO sampler using the existing input handle, never a second request.

The child only reads GPIO and sends bounded binary observations. It cannot touch
the cash journal, Modbus, or application balances. Missing samples remain gaps.
"""
import argparse
import fcntl
import math
import os
from pathlib import Path
from queue import Full
import select
import struct
import subprocess
import sys
import threading
import time

from bill_level_reader import LevelReader, LevelEvent

GET_VALUES = 0xC040B408  # Linux GPIO v1: GPIOHANDLE_GET_LINE_VALUES_IOCTL, 64 bytes.
FRAME = struct.Struct('!BdddQQB')


def gpio_fd(line):
    # gpiod==1.5.4 does not expose its input FD publicly. Refuse unknown bindings;
    # do not request the line again or fall back silently to the old thread.
    fd = line._throw_if_null_and_get_m_line().fd_handle.fd
    if type(fd) is not int or fd < 0:
        raise ValueError('Unsupported GPIO input handle')
    os.fstat(fd)
    return fd


def sample(fd, output, active_low, initial_active, gap_limit_ms):
    nice = int(os.getenv('IO_BILL_SAMPLER_NICE', '0'))
    if not -10 <= nice <= 0:raise ValueError('Unsupported sampler priority')
    if nice:
        # Only the read-only sampler gets a higher normal priority. It still
        # sleeps each iteration and never switches the container to realtime.
        os.setpriority(os.PRIO_PROCESS, 0, nice)
    buffer = bytearray(64)
    os.set_blocking(output, False)
    previous = initial_active
    last = time.monotonic()
    report_at = last
    samples = gaps = 0
    maximum = 0.0
    while True:
        fcntl.ioctl(fd, GET_VALUES, buffer, True)
        value = buffer[0]
        if value not in (0, 1):raise ValueError('Invalid GPIO level')
        now = time.monotonic()
        gap = (now-last)*1000
        if gap < 0:raise ValueError('GPIO clock reversed')
        maximum = max(maximum, gap);samples += 1
        uncertain = gap > gap_limit_ms
        gaps += int(uncertain)
        active = value == 0 if active_low else value != 0
        changed = active != previous
        kind = 1 if changed or uncertain else 2
        if kind == 1 or now >= report_at:
            flags = int(active) | (int(changed) << 1) | (int(uncertain) << 2)
            packet = FRAME.pack(kind, now, gap, maximum, samples, gaps, flags)
            if os.write(output, packet) != len(packet):raise OSError('Incomplete GPIO observation')
            report_at = now+.25
        previous = active;last = now
        time.sleep(.002)


class ProcessLevelReader(LevelReader):
    restart_for_settings = True
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = None
        self._pipe = None
        self._child_samples = 0
        self._child_maximum = 0.0
        self._child_gaps = 0
        self._started = threading.Event()

    def start(self):
        fd = gpio_fd(self.line)
        read_fd, write_fd = os.pipe()
        self._pipe = read_fd
        args = [sys.executable, '-u', str(Path(__file__).resolve()),
                '--gpio-fd', str(fd), '--stream-fd', str(write_fd),
                '--active-low', str(int(self.active_low)),
                '--initial-active', str(int(self.previous)), '--gap-ms', str(self.gap_limit_ms)]
        try:
            self.process = subprocess.Popen(args, pass_fds=(fd, write_fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True)
        except Exception:
            os.close(read_fd);self._pipe = None;raise
        finally:os.close(write_fd)
        self.thread = threading.Thread(target=self._receive, daemon=True, name='bill-sampler-pipe')
        self.thread.start()
        if not self._started.wait(3) or self.error:
            self.close();raise RuntimeError('Isolated GPIO sampler failed to start')

    def _packet(self, data):
        kind, at, gap, maximum, samples, gaps, flags = FRAME.unpack(data)
        if (kind not in (1, 2) or flags & ~7 or not all(math.isfinite(v) for v in (at, gap, maximum))
                or min(at, gap, maximum) < 0 or samples < self._child_samples):
            raise ValueError('Invalid GPIO sampler observation')
        with self.state_lock:
            if at < self.last_at:raise ValueError('GPIO clock reversed')
            self.last_at = at
            self._child_samples = samples;self._child_maximum = maximum;self._child_gaps = gaps
            if kind == 1:
                try:self.queue.put_nowait(LevelEvent(bool(flags & 1), at, bool(flags & 2), bool(flags & 4)))
                except Full:
                    self.error = 'reader_overflow';return
                self.available.set()
        self._started.set()

    def _receive(self):
        pending = b'';last = time.monotonic()
        try:
            while not self.stop.is_set() and not self.error:
                ready, _, _ = select.select([self._pipe], [], [], .25)
                if not ready:
                    if time.monotonic()-last > 2:
                        self.error = 'reader_timeout';break
                    continue
                block = os.read(self._pipe, FRAME.size*128)
                if not block:
                    if not self.stop.is_set():self.error = 'reader_failed'
                    break
                last = time.monotonic();pending += block
                while len(pending) >= FRAME.size:
                    self._packet(pending[:FRAME.size]);pending = pending[FRAME.size:]
        except Exception:
            if not self.stop.is_set():self.error = 'reader_failed'
        finally:
            self._started.set();self.available.set()
            if self._pipe is not None:
                os.close(self._pipe);self._pipe = None

    def close(self):
        self.stop.set()
        if self.process:
            if self.process.poll() is None:self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        if self.thread:self.thread.join(timeout=3)

    def reconfigure(self, active_low, initial_active, at, gap_limit_ms):
        # Caller holds bill_lock but not state_lock; finish the old collector
        # before replacing its pipe and state. The GPIO request stays owned.
        line = self.line
        self.close()
        if self.thread and self.thread.is_alive():raise RuntimeError('Old sampler collector still running')
        self.__init__(line,active_low,initial_active,at,gap_limit_ms)
        self.start()

    def snapshot(self):
        with self.state_lock:
            return {'reader':'level-process','samples':self._child_samples,
                    'max_sample_gap_ms':round(self._child_maximum,3),
                    'uncertain_gaps':self._child_gaps,'reader_error':self.error,
                    'queued_transitions':self.queue.qsize(),
                    'sampler_nice':int(os.getenv('IO_BILL_SAMPLER_NICE','0')),
                    'sampler_pid':self.process.pid if self.process else None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpio-fd', type=int, required=True)
    parser.add_argument('--stream-fd', type=int, required=True)
    parser.add_argument('--active-low', type=int, choices=(0,1), required=True)
    parser.add_argument('--initial-active', type=int, choices=(0,1), required=True)
    parser.add_argument('--gap-ms', type=float, required=True)
    args = parser.parse_args()
    try:sample(args.gpio_fd,args.stream_fd,bool(args.active_low),bool(args.initial_active),args.gap_ms)
    except Exception:raise SystemExit(2)
