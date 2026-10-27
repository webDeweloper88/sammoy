#!/usr/bin/env python3
"""Set only CL3566 IO5 to input before containers start. No output writes."""
from pathlib import Path
import time
import subprocess

path=Path('/sys/external_gpio/jwsioc_inout_gpio5')
# Vendor ships this module outside the versioned modprobe tree.
if not path.exists() and not Path('/sys/module/jwsioc').exists():
    subprocess.run(['/usr/sbin/insmod', '/lib/modules/jwsioc.ko'], check=True)
for _ in range(600):
    if path.exists():break
    time.sleep(.1)
else:raise SystemExit('CL3566 vendor GPIO interface missing')
path.write_text('0\n')
if path.read_text().strip()!='0':raise SystemExit('CL3566 IO5 input mode not confirmed')
