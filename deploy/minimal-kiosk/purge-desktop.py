import argparse,os
from pathlib import Path
import subprocess,json
state=Path('/var/lib/sammoy2-minimal-kiosk')
installed=set(subprocess.check_output(['dpkg-query','-W','-f=${binary:Package} ${db:Status-Status}\n'],text=True).splitlines())
names='task-kde-desktop kde-standard kde-plasma-desktop plasma-desktop plasma-workspace kwin-x11 akregator kmail korganizer konqueror kdeconnect plasma-discover dolphin kate konsole khelpcenter okular juk dragonplayer sweeper gwenview kaddressbook kcalc kwrite kde-spectacle'.split()
names=[n for n in names if n+' installed' in installed]
plan=subprocess.check_output(['apt-get','-s','purge',*names],text=True)
removed=[x.split()[1] for x in plan.splitlines() if x.startswith(('Purg ','Remv '))]
protected=('network','openbox','xserver','linux','docker','containerd','python3','systemd','plymouth','libinput','task-a733','task-allwinner','task-radxa')
assert not any(n == 'sddm' or n.startswith(protected) for n in removed), 'Protected package in removal plan'
state.joinpath('desktop-purge-plan.txt').write_text(plan)
state.joinpath('desktop-purge-packages.json').write_text(json.dumps(names))
print('Desktop-only removal plan:',len(removed),'packages')
print('\n'.join(removed))

parser=argparse.ArgumentParser()
parser.add_argument('--apply',action='store_true')
if parser.parse_args().apply:
 assert os.geteuid()==0, 'Root required'
 subprocess.run(['pgrep','-u','kiosk','-x','openbox'],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['systemctl','is-active','--quiet','sammoy2-kiosk.service'],check=True)
 keep='sddm openbox xserver-xorg xserver-xorg-core xserver-xorg-input-libinput x11-xserver-utils x11-utils xinput xauth dbus-x11 network-manager openssh-server python3 plymouth fonts-dejavu-core'.split()
 keep=[n for n in keep if n+' installed' in installed]
 subprocess.run(['apt-mark','manual',*keep],check=True)
 state.joinpath('packages-before-desktop-removal.txt').write_text(subprocess.check_output(['dpkg-query','-W','-f=${binary:Package} ${Version}\n'],text=True))
 subprocess.run(['apt-get','-y','purge',*names],env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'},check=True)
 state.joinpath('desktop-removed').touch()
 print('Desktop applications removed; no autoremove or driver removal performed')
