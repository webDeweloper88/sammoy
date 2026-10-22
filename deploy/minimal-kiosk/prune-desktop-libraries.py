#!/usr/bin/python3
"""Installer-only unused desktop dependency cleanup, after a proven minimal boot."""
import os
from pathlib import Path
import subprocess
import re
assert os.geteuid()==0
state=Path('/var/lib/sammoy2-minimal-kiosk')
assert (state/'desktop-removed').exists()
subprocess.run(['pgrep','-u','kiosk','-x','openbox'],check=True,stdout=subprocess.DEVNULL)
# Retain the graphics toolkit and server utilities even if desktop metapackages
# previously owned them. Never autoremove a board's kernel/driver metapackages.
installed=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package} ${db:Status-Status}\n'],text=True).splitlines()
installed_names={line.split()[0].split(':')[0] for line in installed if line.endswith(' installed')}
keep=[n for n in ('xorg','xinit','x11-session-utils','libxcb-cursor0','libxcb-record0','libqt5concurrent5','libgl1-mesa-dri','libegl-mesa0','libgbm1','libgles2','libvulkan1','sshfs') if n in installed_names]
keep += [line.split()[0] for line in installed if line.endswith(' installed') and line.startswith(('task-a733','task-allwinner','task-radxa','linux-image','linux-dtb','radxa-'))]
subprocess.run(['apt-mark','manual',*keep],check=True,stdout=subprocess.DEVNULL)
# Preserve libraries linked by the custom Chromium binary, which is outside dpkg.
linked=set()
for line in subprocess.check_output(['ldd','/usr/local/chromium/bin/chrome'],text=True).splitlines():
 match=re.search(r'=> (/[^ ]+)',line)
 if not match:continue
 path=match.group(1)
 for variant in (path,str(Path(path).resolve())):
  result=subprocess.run(['dpkg-query','-S',variant],capture_output=True,text=True)
  if result.returncode==0:
   linked.update(x.rsplit(': ',1)[0] for x in result.stdout.splitlines());break
if linked:subprocess.run(['apt-mark','manual',*sorted(linked)],check=True,stdout=subprocess.DEVNULL)
plan=subprocess.check_output(['apt-get','-s','autoremove','--purge'],text=True)
removed=[line.split()[1] for line in plan.splitlines() if line.startswith(('Remv ','Purg '))]
protected=('xserver','linux','radxa','task-a733','task-allwinner','task-radxa','docker','containerd','python3','libinput','network-manager','openssh','systemd','plymouth','sddm','openbox','xorg','xinit','x11-')
assert not any(n.startswith(protected) for n in removed), 'Protected runtime package in removal plan'
assert len(removed)<=250, 'Unexpectedly large cleanup; review dependencies'
state.joinpath('unused-desktop-plan.txt').write_text(plan)
print('Validated unused desktop dependencies:',len(removed),flush=True)
subprocess.run(['apt-get','-y','autoremove','--purge'],env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'},check=True)
