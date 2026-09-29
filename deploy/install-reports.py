#!/usr/bin/env python3
"""Provision reporting credentials, a read-only SQL role and LAN binding.
Run with sudo from this checkout before docker compose build/up.
No wash settings, tariffs, users or outputs are changed.
"""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
from urllib.parse import quote
ROOT=Path(__file__).resolve().parents[1]
def run(*args,**kwargs):return subprocess.run(args,cwd=ROOT,check=True,text=True,**kwargs)
if os.geteuid()!=0:raise SystemExit('Run with sudo')
path=ROOT/'.env'
values={}
for line in path.read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k,v=line.split('=',1);v=shlex.split(v);values[k]=v[0] if v else ''
updates={}
for key in ('TELEGRAM_SETUP_KEY','REPORT_API_KEY','REPORT_DB_PASSWORD'):
    if not values.get(key):updates[key]=secrets.token_hex(32)
values.update(updates)
route=json.loads(run('ip','-j','route','get','1.1.1.1',capture_output=True).stdout)[0]
address=route.get('prefsrc') or route.get('src');device=route['dev']
info=json.loads(run('ip','-j','address','show','dev',device,capture_output=True).stdout)
entry=next(a for item in info for a in item['addr_info'] if a.get('local')==address)
network=ipaddress.ip_network(f"{address}/{entry['prefixlen']}",strict=False)
updates['REPORT_LAN_CIDR']=str(network);updates['REPORT_BIND_IP']=address
updates['REPORT_POSTGRES_DSN']='postgresql://sammoy_reports:'+quote(values['REPORT_DB_PASSWORD'],safe='')+'@postgres:5432/'+quote(values['POSTGRES_DB'],safe='')
def ident(s):return '"'+s.replace('"','""')+'"'
def literal(s):return "'"+s.replace("'","''")+"'"
sql="""SELECT 'CREATE ROLE sammoy_reports LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='sammoy_reports')\\gexec
ALTER ROLE sammoy_reports PASSWORD %s;
ALTER ROLE sammoy_reports SET default_transaction_read_only=on;
GRANT CONNECT ON DATABASE %s TO sammoy_reports;
GRANT USAGE ON SCHEMA public TO sammoy_reports;
GRANT SELECT ON payments,wash_sessions,mode_usage,system_events TO sammoy_reports;
"""%(literal(values['REPORT_DB_PASSWORD']),ident(values['POSTGRES_DB']))
run('docker','compose','exec','-T','postgres','psql','-v','ON_ERROR_STOP=1','-U',values['POSTGRES_USER'],'-d',values['POSTGRES_DB'],input=sql,stdout=subprocess.DEVNULL)
lines=[line for line in path.read_text().splitlines() if line.split('=',1)[0] not in updates]
lines.extend(k+'='+shlex.quote(v) for k,v in updates.items())
path.write_text('\n'.join(lines)+'\n');path.chmod(0o600)
print('Read-only reporting role and LAN discovery configured. Credentials saved without displaying them.')
