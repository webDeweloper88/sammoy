#!/usr/bin/env python3
"""Keep application DNS independent of the DHCP server captured at container start.

Install only during maintenance: initial installation restarts Docker. At boot,
refresh only rebinds systemd-resolved after the Docker bridge exists.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess

ROOT=Path('/opt/sammoy/sammoy2')
DROPIN=Path('/etc/systemd/resolved.conf.d/60-labrix-container-dns.conf')
UNIT='''[Unit]
Description=LABRIX DNS listener for application containers
Requires=docker.service
Wants=systemd-resolved.service
After=docker.service systemd-resolved.service
Before=sammoy2-post.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/sammoy/sammoy2/deploy/install-container-dns.py --refresh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
'''


def bridge_address(network):
    addresses=[x.get('Gateway') for x in network.get('IPAM',{}).get('Config',[])]
    for value in addresses:
        if value and isinstance(ipaddress.ip_address(value),ipaddress.IPv4Address):
            return str(ipaddress.ip_address(value))
    raise RuntimeError('Docker bridge IPv4 gateway missing')


def daemon_configuration(existing,address):
    updated=dict(existing)
    if updated.get('dns') and updated['dns']!=[address]:
        raise RuntimeError('Existing custom Docker DNS requires operator review')
    updated['dns']=[address]
    return updated


def command(*args):
    return subprocess.run(args,check=True,text=True)


def require_resolver():
    load_state=subprocess.check_output(['systemctl','show','--property=LoadState','--value','systemd-resolved.service'],text=True).strip()
    if load_state!='loaded':
        raise RuntimeError('Install systemd-resolved before configuring container DNS')


def refresh():
    require_resolver()
    network=json.loads(subprocess.check_output(['docker','network','inspect','bridge'],text=True))[0]
    address=bridge_address(network)
    DROPIN.parent.mkdir(parents=True,exist_ok=True)
    DROPIN.write_text('[Resolve]\nDNSStubListenerExtra='+address+'\n')
    command('systemctl','restart','systemd-resolved.service')
    return address


def install():
    require_resolver()
    # No container stop or restart while a paid session or installation action is active.
    import urllib.request
    state=json.load(urllib.request.urlopen('http://127.0.0.1:8090/api/wash/state',timeout=4))['state']
    if any(state.get(k) for k in ('creditSum','activeMode','armedMode','activeSessionId','walletTransferPending','requestedOutput')):
        raise RuntimeError('Install container DNS only on an idle station without customer credit')
    network=json.loads(subprocess.check_output(['docker','network','inspect','bridge'],text=True))[0]
    address=bridge_address(network)
    config=Path('/etc/docker/daemon.json')
    existing=json.loads(config.read_text()) if config.exists() else {}
    updated=daemon_configuration(existing,address)
    refresh()
    config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text(json.dumps(updated,indent=2)+'\n')
    unit=Path('/etc/systemd/system/sammoy2-container-dns.service')
    unit.write_text(UNIT)
    required=Path('/etc/systemd/system/sammoy2-post.service.d/container-dns.conf')
    required.parent.mkdir(parents=True,exist_ok=True)
    required.write_text('[Unit]\nRequires=sammoy2-container-dns.service\nAfter=sammoy2-container-dns.service\n')
    command('systemctl','daemon-reload')
    command('systemctl','enable','sammoy2-container-dns.service')
    command('systemctl','restart','docker.service')
    command('systemctl','restart','sammoy2-container-dns.service')
    print('Container DNS now uses the host resolver at '+address)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root is required')
    if args.refresh:refresh()
    else:install()
