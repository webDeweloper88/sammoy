"""Read-only CL3566 IO5 source. Host provisioning owns direction/pullups.

No sysfs writes, no gpiod request, no inference of missing pulses.
"""
import os

MODE = '/sys/external_gpio/jwsioc_inout_gpio5'
VALUE = '/sys/external_gpio/jwsioc_gpio5'


def read_level(fd, mode_fd):
    if os.pread(mode_fd, 16, 0).strip() != b'0':
        raise RuntimeError('Vendor bill GPIO is not input')
    value = os.pread(fd, 16, 0).strip()
    if value not in (b'0', b'1'):
        raise RuntimeError('Invalid vendor GPIO level')
    return int(value)


class VendorSysfsLine:
    def __init__(self):
        self.fd = self.mode_fd = None
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            self.mode_fd = os.open(MODE, flags)
            self.fd = os.open(VALUE, flags)
            self.get_value()
        except BaseException:
            self.release()
            raise

    def get_value(self):
        if self.fd is None or self.mode_fd is None:
            raise RuntimeError('Vendor bill GPIO is closed')
        return read_level(self.fd, self.mode_fd)

    def event_wait(self, timeout):
        return False  # Level sampler owns transitions; sysfs has no edge queue.

    def release(self):
        for name in ('fd', 'mode_fd'):
            fd = getattr(self, name)
            setattr(self, name, None)
            if fd is not None:
                os.close(fd)
