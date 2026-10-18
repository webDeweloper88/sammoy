import asyncio
from datetime import date
import httpx
import pytest
from fastapi.testclient import TestClient
from app import container_setup as setup
from app.common.config import HubConfig, PostConfig, SiteConfig
from app.hub.aggregator import ReportAggregator
from test_core import sample_post

@pytest.fixture
def configured(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'ENV_PATH',tmp_path/'reports.env')
    monkeypatch.setattr(setup,'POSTS_PATH',tmp_path/'posts.yaml')
    monkeypatch.setattr(setup,'DATA_PATH',tmp_path/'hub.sqlite3')
    monkeypatch.setattr(setup,'LOCK',asyncio.Lock())
    monkeypatch.setenv('TELEGRAM_SETUP_KEY','test-secret')
    monkeypatch.setenv('REPORT_LAN_CIDR','192.168.10.0/29')
    monkeypatch.setattr(setup,'active',lambda name:True)
    monkeypatch.setattr(setup,'control',lambda *args:None)
    setup.write_env({'SITE_ID':'SITE-1','SITE_NAME':'Test','POST_ID':'POST-01','SITE_REPORT_API_KEY':'shared-secret','TELEGRAM_ENABLED':'false'})
    setup.write_posts('SITE-1','Test',[{'id':'POST-01','name':'Post 1','host':'127.0.0.1','port':8091,'api_key_env':'SITE_REPORT_API_KEY','enabled':True}])
    return TestClient(setup.app,headers={'Authorization':'Bearer test-secret'})

def test_setup_auth_and_secret_redaction(configured):
    assert configured.get('/status',headers={'Authorization':''}).status_code==401
    setup.write_env({'TELEGRAM_BOT_TOKEN':'never-echo-this'})
    r=configured.get('/status')
    assert r.status_code==200
    assert 'never-echo-this' not in r.text
    assert 'shared-secret' not in r.text

def test_environment_roundtrip(configured):
    value="text with ' apostrophe \\ and spaces"
    setup.write_env({'SITE_NAME':value})
    assert setup.read_env()['SITE_NAME']==value
    assert setup.ENV_PATH.stat().st_mode & 0o777 == 0o600

def test_pairing_and_reset(configured):
    assert configured.post('/pairing',json={}).status_code==409
    setup.write_env({'TELEGRAM_ENABLED':'true','TELEGRAM_BOT_USERNAME':'examplebot'})
    r=configured.post('/pairing',json={});assert r.status_code==200
    raw=r.json()['pairing_url'].split('start=')[1]
    store=setup.PairingStore(setup.DATA_PATH)
    assert store.claim(raw,123,'test','Owner')
    assert configured.post('/pairing',json={}).status_code==409
    assert configured.post('/pairing',json={'reset_owner':True}).status_code==200
    assert not store.is_owner(123)

def test_discovery_preserves_offline_and_excludes_other_site(configured,monkeypatch):
    setup.write_posts('SITE-1','Test',setup.posts()+[{'id':'POST-03','name':'Post 3','host':'192.168.10.3','port':8091,'api_key_env':'SITE_REPORT_API_KEY','enabled':True}])
    original=httpx.AsyncClient
    def handle(req):
        host=req.url.host
        if host in ('127.0.0.1','192.168.10.1'):d={'site_id':'SITE-1','post_id':'POST-01','node_id':'node1'}
        elif host=='192.168.10.2':d={'site_id':'SITE-1','post_id':'POST-02','node_id':'node2'}
        else:d={'site_id':'OTHER','post_id':'POST-04','node_id':'other'}
        assert req.headers['Authorization']=='Bearer shared-secret'
        return httpx.Response(200,json=d)
    monkeypatch.setattr(setup.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    r=configured.post('/discover');assert r.status_code==200,r.text
    assert [p['id'] for p in r.json()['posts']]==['POST-01','POST-02','POST-03']

def test_discovery_rejects_duplicate_without_overwrite(configured,monkeypatch):
    before=setup.POSTS_PATH.read_text();original=httpx.AsyncClient
    def handle(req):return httpx.Response(200,json={'site_id':'SITE-1','post_id':'POST-01','node_id':req.url.host})
    monkeypatch.setattr(setup.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    assert configured.post('/discover').status_code==409
    assert setup.POSTS_PATH.read_text()==before

@pytest.mark.asyncio
async def test_report_identity_mismatch_rejected(monkeypatch):
    monkeypatch.setenv('TEST_KEY','key')
    config=HubConfig(site=SiteConfig(id='SITE-1',name='Site'),posts=[])
    post=PostConfig(id='POST-02',name='Post 2',host='127.0.0.1',api_key_env='TEST_KEY')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=sample_post('POST-01').model_dump(mode='json')))) as client:
        result=await ReportAggregator(config)._fetch(client,post,'daily',date(2026,9,29))
    assert result.status=='offline'
    assert result.error=='invalid_response'


def test_reset_invalidates_unused_pairing_links(configured):
    store=setup.PairingStore(setup.DATA_PATH)
    raw,_=store.create_token(10)
    store.reset_owner()
    assert not store.claim(raw,999,'old-link','Old')

def test_discovery_uses_current_network(configured,monkeypatch):
    hosts=[];original=httpx.AsyncClient
    def handle(req):
        hosts.append(req.url.host)
        return httpx.Response(200,json={'site_id':'SITE-1','post_id':'POST-01','node_id':'local'})
    monkeypatch.setattr(setup.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    assert configured.post('/discover',json={'cidr':'10.20.30.0/30'}).status_code==200
    assert set(hosts)=={'10.20.30.1','10.20.30.2','127.0.0.1'}
    assert configured.post('/discover',json={'cidr':'8.8.8.0/24'}).status_code==409


def test_leadership_does_not_erase_bot_configuration(configured):
    setup.write_env({'TELEGRAM_ENABLED':'true','TELEGRAM_BOT_TOKEN':'fixture-token'})
    r=configured.post('/leadership',json={'active':False,'primary_post':7})
    assert r.status_code==200
    assert not configured.get('/status').json()['enabled']
    assert setup.read_env()['TELEGRAM_BOT_TOKEN']=='fixture-token'
    assert setup.read_env()['TELEGRAM_ENABLED']=='true'
    r=configured.post('/leadership',json={'active':True,'primary_post':7})
    assert r.status_code==200
    assert configured.get('/status').json()['enabled']


def test_report_backup_preserves_pairing_notifications_without_enabling_standby(configured):
    store=setup.PairingStore(setup.DATA_PATH)
    raw,_=store.create_token(10,'fixture');assert store.claim(raw,123,'owner','Owner')
    store.set_state('automatic_daily_report_date','2026-10-07')
    setup.write_env({'TELEGRAM_BOT_TOKEN':'fixture-token','TELEGRAM_ENABLED':'true','TELEGRAM_LEADER':'false'})
    snapshot=configured.get('/backup/export').json()
    store.reset_owner();setup.write_env({'TELEGRAM_BOT_TOKEN':''})
    assert configured.post('/backup/import',json=snapshot).status_code==200
    assert setup.PairingStore(setup.DATA_PATH).owner()['telegram_user_id']==123
    assert setup.PairingStore(setup.DATA_PATH).state('automatic_daily_report_date')=='2026-10-07'
    assert setup.read_env()['TELEGRAM_BOT_TOKEN']=='fixture-token'
    assert not configured.get('/status').json()['enabled']
    snapshot['site_id']='OTHER'
    assert configured.post('/backup/import',json=snapshot).status_code==409
