#!/usr/bin/env python3
"""Isolated test runner: never mounts .env, live volumes or GPIO devices."""
import argparse,os,shlex,shutil,subprocess,tempfile,time,uuid
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[2]
def docker(*args,**kw):return subprocess.run(shlex.split(os.environ.get('SAMMOY_DOCKER','docker'))+list(args),check=True,**kw)
def engine_args(stage,network='none'):
 return ['run','--rm','--network',network,'--read-only','--tmpfs','/tmp:rw,size=256m','-e','WASH_ENGINE_DEFAULT_OWNER_PASSWORD=test-only-owner','-e','WASH_ENGINE_DEFAULT_ADMIN_PASSWORD=test-only-admin','-e','WASH_ENGINE_KIOSK_ASSETS_DIR=/tmp/kiosk-assets','-e','PYTHONPATH=/app:/suite/tests:/suite/integration','-v',str(PROJECT/'services/wash-engine/app')+':/app/app:ro','-v',str(stage)+':/suite:ro','-w','/suite']
def units(stage):
 docker(*engine_args(stage),'sammoy2-wash-engine:latest','python','-m','unittest','discover','-s','tests','-p','test_*.py','-q')
 docker('run','--rm','--network','none','--read-only','--tmpfs','/tmp:rw,size=32m','-e','PYTHONPATH=/suite','-v',str(PROJECT/'services/io-helper')+':/suite:ro','-w','/suite','sammoy2-io-helper:latest','python','-m','unittest','test_input_filter','test_controller_lease','test_output_safety','test_output_test','test_pulse_journal','test_rfid','test_hardware_profile','-q')
 subprocess.run(['python3','-m','unittest','discover','-s',str(PROJECT/'deploy/maintenance'),'-p','test_*.py','-q'],check=True)
def postgres(stage):
 nonce=uuid.uuid4().hex;network='sammoy-check-'+nonce;container=network+'-pg';password=uuid.uuid4().hex
 docker('network','create','--internal',network,stdout=subprocess.DEVNULL)
 try:
  docker('run','-d','--name',container,'--network',network,'--network-alias','test-pg','--tmpfs','/var/lib/postgresql/data:rw,size=512m','-e','POSTGRES_USER=test','-e','POSTGRES_PASSWORD='+password,'postgres:16-alpine',stdout=subprocess.DEVNULL)
  for _ in range(60):
   try:docker('exec',container,'pg_isready','-U','test',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);break
   except subprocess.CalledProcessError:time.sleep(.2)
  else:raise RuntimeError('Disposable PostgreSQL failed to start')
  for name in ['wallet_test','retention_test']:docker('exec',container,'psql','-U','test','-d','test','-c','CREATE DATABASE '+name,stdout=subprocess.DEVNULL)
  args=engine_args(stage,network)
  for key,dbname in [('WALLET_TEST_DSN','wallet_test'),('RETENTION_TEST_DSN','retention_test'),('CASH_TEST_DSN','retention_test'),('FINANCIAL_TEST_DSN','retention_test'),('REPORT_TEST_DSN','retention_test')]:args+=['-e',key+'=postgresql://test:'+password+'@test-pg/'+dbname]
  args+=['-e','WASH_ENGINE_POSTGRES_HOST=test-pg','-e','WASH_ENGINE_POSTGRES_DB=wallet_test','-e','WASH_ENGINE_POSTGRES_USER=test','-e','WASH_ENGINE_POSTGRES_PASSWORD='+password]
  modules=['test_cash_ingest_postgres','test_financial_ids_postgres','test_retention_postgres','test_owner_reports_postgres','test_local_import_postgres','test_vip_import_postgres','test_wallet_postgres','test_wallet_replication_postgres','test_wallet_proofs_postgres','test_wallet_post_adapter_postgres','test_bonus_postgres','test_bonus_wallet_postgres','test_wallet_http']
  docker(*args,'sammoy2-wash-engine:latest','python','-m','unittest',*modules,'-q')
 finally:
  docker('rm','-f',container,stdout=subprocess.DEVNULL)
  docker('network','rm',network,stdout=subprocess.DEVNULL)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('suite',choices=['unit','postgres','all']);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='sammoy-check-') as folder:
  stage=Path(folder);(stage/'tests').mkdir()
  for source in (PROJECT/'services/wash-engine/tests').glob('*.py'):shutil.copy2(source,stage/'tests'/source.name)
  shutil.copytree(PROJECT/'services/wash-engine/tests/integration',stage/'integration',ignore=shutil.ignore_patterns('test_database_flows.py','__pycache__'))
  if a.suite in ('unit','all'):units(stage)
  if a.suite in ('postgres','all'):postgres(stage)
if __name__=='__main__':main()
