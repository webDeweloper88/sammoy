#!/usr/bin/env python3
"""Fixed CL3566 layout action; called under apply-device-profile.sh lock."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from board_runtime import ROOT, board, compose, ready


def get(path):
    req=urllib.request.Request('http://127.0.0.1:8090/api/'+path,headers={'X-Commissioning-Client-IP':'127.0.0.1'})
    with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)


def run(args):
    return subprocess.run(args,cwd=ROOT,check=True,capture_output=True,text=True)


def off_proof():
    code="import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:8080/io',timeout=3));assert d.get('modbus_ok') is True and len(d['outputs'])==8 and all(v is False for v in d['outputs'].values())"
    for _ in range(30):
        try:run(['docker','exec','sammoy2-io-helper','python','-c',code]);return
        except subprocess.CalledProcessError:time.sleep(1)
    raise RuntimeError('All-output OFF readback not confirmed')


def apply():
    if board()!='cl3566-a-e' or not ready():raise RuntimeError('CL3566 resources/input mode not ready')
    state=get('wash/state')['state']
    if any(state.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld','vipRemainingSeconds')):
        raise RuntimeError('Finish the customer session/card operation first')
    target=get('commissioning/device')['requested']['type']
    if target not in ('wash','dry_fog'):raise RuntimeError('Unknown device type')
    if target=='dry_fog':
        c=get('commissioning/wallet')['configuration']
        if not c.get('device_wallet_enabled') or c.get('device_types',{}).get(str(c['local_post']))!=target:
            raise RuntimeError('Configure station types on primary first')
    layout='dry-fog' if target=='dry_fog' else 'nfc-relay'
    cmd=compose(layout)
    run(cmd+['config','--quiet'])
    for image in ('sammoy2-wash-engine:latest','sammoy2-io-helper:latest'):
        run(['docker','image','inspect',image])
    stopped=False
    marker=ROOT/'.hardware-profile'
    previous=marker.read_text() if marker.exists() else 'factory-only\n'
    map_path=ROOT/'config'/('io-map.cl3566-fog.yaml' if target=='dry_fog' else 'io-map.cl3566.yaml')
    previous_map=map_path.read_bytes()
    (ROOT/('.cl3566-map-before-apply.yaml')).write_bytes(previous_map)
    try:
        run(['docker','stop','sammoy2-wash-engine']);stopped=True
        current=subprocess.run(['docker','inspect','--format','{{.State.Running}}','sammoy2-io-helper'],capture_output=True,text=True)
        if current.returncode==0 and current.stdout.strip()=='true':
            off_proof()
            code="import json,yaml;print(json.dumps(yaml.safe_load(open('/config/io-map.yaml'))['bill_acceptor']))"
            current_bill=json.loads(run(['docker','exec','sammoy2-io-helper','python','-c',code]).stdout)
            if current_bill.get('source')!='vendor-sysfs':
                raise RuntimeError('Current helper does not use the CL3566 GPIO source')
            map_name='io-map.cl3566-fog.yaml' if target=='dry_fog' else 'io-map.cl3566.yaml'
            run(['python3','deploy/preserve-bill-config.py','config/'+map_name,json.dumps(current_bill)])
        run(cmd+['up','-d','--no-build','--pull','never','--no-deps','--wait','--wait-timeout','120','io-helper'])
        off_proof()
        (ROOT/'.hardware-profile.before-cl3566-apply').write_text(previous)
        temp=ROOT/'.hardware-profile.pending';temp.write_text(layout+'\n');os.replace(temp,marker)
        run(cmd+['up','-d','--no-build','--pull','never','--no-deps','--wait','--wait-timeout','120','wash-engine'])
        for _ in range(30):
            try:
                state=get('wash/state')['state']
                if state.get('deviceType')==target and state.get('lastIoOk') and not state.get('creditSum') and not state.get('requestedOutput'):
                    return
            except Exception:pass
            time.sleep(1)
        raise RuntimeError('CL3566 engine readiness not confirmed')
    except BaseException:
        marker.write_text(previous)
        map_path.write_bytes(previous_map)
        # Expose the API for service; never issue an ON command on recovery.
        if stopped:subprocess.run(['docker','start','sammoy2-wash-engine'],capture_output=True)
        raise


if __name__=='__main__':apply()
