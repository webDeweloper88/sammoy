#!/usr/bin/env python3
"""Enable the tested SDA pin3 / SCL pin5 overlay, preserving rescue boot."""
from pathlib import Path
import hashlib,os,re,shutil
OVERLAY='/boot/dtbo/sun60iw2p1-twi7.dtbo'
EXPECTED='01d9de77e4a96644a3985db10ca0782235de5de17075e5a2fc24b48391d509d8'

def update(text):
    default=re.search(r'^\s*default\s+(\S+)\s*$',text,re.M|re.I)
    if not default:raise ValueError('No default boot entry')
    sections=list(re.finditer(r'^label\s+(\S+).*$',text,re.M|re.I))
    for i,section in enumerate(sections):
        if section.group(1)!=default.group(1):continue
        end=sections[i+1].start() if i+1<len(sections) else len(text)
        part=text[section.start():end]
        if not re.search(r'^\s*linux\s+.*5\.15\.147-21-a733',part,re.M):raise ValueError('Kernel differs from the tested board')
        line=re.search(r'^\s*fdtoverlays[^\n]*',part,re.M)
        if line:
            if OVERLAY in line.group(0).split():return text
            part=part[:line.end()]+' '+OVERLAY+part[line.end():]
        else:
            at=part.index('\n')+1;part=part[:at]+'\tfdtoverlays '+OVERLAY+'\n'+part[at:]
        return text[:section.start()]+part+text[end:]
    raise ValueError('Default boot entry not found')

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Root required')
    source=Path(__file__).resolve().parent/'overlays/sun60iw2p1-twi7.dtbo'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED:raise SystemExit('Overlay checksum mismatch')
    config=Path('/boot/extlinux/extlinux.conf');old=config.read_text();new=update(old)
    destination=Path(OVERLAY);destination.parent.mkdir(exist_ok=True)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest()!=EXPECTED:raise SystemExit('Existing overlay differs; refusing overwrite')
    shutil.copyfile(source,destination)
    if new!=old:
        backup=config.with_name('extlinux.conf.before-sammoy-nfc')
        if not backup.exists():shutil.copy2(config,backup)
        temp=config.with_suffix('.sammoy.tmp');temp.write_text(new);temp.chmod(config.stat().st_mode & 0o777);os.replace(temp,config)
    os.sync();print('NFC bus overlay prepared. Takes effect after reboot; GPIO bill input unchanged.')
