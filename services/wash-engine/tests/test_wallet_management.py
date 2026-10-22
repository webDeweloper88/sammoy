from contextlib import contextmanager,nullcontext
from copy import deepcopy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import current_user
from app import wallet_management as m
from app.wallet_domain import WalletConflict
from app.wallet_replication import WalletUnavailable

PROOF={'proof_version':2,'pending_count':0,'operation_count':1,
       'journal_digest':'a'*64,'state_digest':'b'*64}


class Node:
    def __init__(self,cluster,post):
        self.cluster=cluster;self.post=post;self.control_lock=threading.RLock()
        self.cfg={'enabled':True,'site_id':'SITE','local_post':post,'primary_post':1,
                  'standby_post':3 if post==3 else 2,'generation':1 if post==3 else 3,
                  'standby_ready':post!=3,'single_node':False,'visit_timeout_minutes':30,
                  'peer_urls':{'1':'http://10.0.0.1','2':'http://10.0.0.2','3':'http://10.0.0.3'}}
        self.proof=deepcopy(PROOF);self.saved=[]
    def configuration(self):return deepcopy(self.cfg)
    def persist_configuration(self,cfg,user,event):
        self.cfg=deepcopy(cfg);self.saved.append(event);self.cluster.events.append((self.post,event))
    @contextmanager
    def store_context(self,cfg,allow_management=False):
        if m.roles(cfg)!=m.roles(self.cfg):raise WalletConflict('stale roles')
        if self.cfg.get('management_pending') and not allow_management:raise WalletUnavailable('paused')
        yield SimpleNamespace(diagnostics=lambda:deepcopy(self.proof),pending_operations=lambda:[])
    def validate_peer_url(self,url):return url
    def rpc(self,cfg,post,action,payload):
        if str(post) not in cfg['peer_urls']:raise WalletUnavailable('Peer address or site key is missing')
        if post in self.cluster.offline:raise WalletUnavailable('physically disconnected')
        previous=self.cluster.current;self.cluster.current=post
        try:result=m.internal(action.removeprefix('management-'),deepcopy(payload),self.cluster.nodes[post].configuration(),cfg['local_post'])
        finally:self.cluster.current=previous
        if self.cluster.drop==action:
            self.cluster.drop=None;raise WalletUnavailable('ack lost')
        return result


class Cluster:
    def __init__(self):
        self.current=1;self.drop=None;self.events=[];self.offline=set()
        self.nodes={p:Node(self,p) for p in (1,2,3)}
    def api(self):return self.nodes[self.current]
    def copy(self,cfg,job):
        target=self.nodes[job['target_post']]
        assert m.roles(target.cfg)==job['after']
        assert target.cfg['management_pending']['stage']=='prepared'
        target.proof=deepcopy(self.nodes[1].proof)
        return deepcopy(target.proof)


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.cluster=Cluster()
        self.patches=[patch.object(m,'api',side_effect=lambda:self.cluster.api()),patch.object(m,'idle'),
                      patch.object(m,'proof_ready',side_effect=lambda cfg,job:self.cluster.copy(cfg,job)),patch.object(m,'worker_lock',threading.Lock()),patch.object(m,'distributed',side_effect=lambda:nullcontext())]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
    def start(self,kind='replace_standby',fenced=False):
        root=self.cluster.nodes[1];target=3 if kind=='replace_standby' else 2
        value=m.Selection(kind=kind,target_post=target,target_url=f'http://10.0.0.{target}',old_standby_fenced=fenced)
        plan=m.preflight(root.configuration(),value)
        job={**value.model_dump(),'request_id':str(uuid4()),'before':plan['before'],'after':plan['after'],
             'peer_urls':plan['peer_urls'],'stage':'checking','actor':'owner','error':None}
        cfg=root.configuration();m.persist(cfg,job,'started')
        return job
    def run_job(self,job):
        self.assertTrue(m.worker_lock.acquire(False));m.run_job(job['request_id'])
    def test_replacement_retires_old_reserve_before_new_reserve_is_ready(self):
        job=self.start();self.run_job(job)
        for post in (1,2,3):self.assertEqual(m.roles(self.cluster.nodes[post].cfg),job['after'])
        self.assertFalse(self.cluster.nodes[2].cfg['standby_ready'])
        self.assertTrue(self.cluster.nodes[3].cfg['standby_ready'])
        self.assertIsNone(self.cluster.nodes[1].cfg['management_pending'])
        events=self.cluster.events
        self.assertLess(events.index((2,'wallet_old_standby_retired')),events.index((3,'wallet_role_change_target_activated')))
    def test_new_standby_address_is_taken_from_saved_plan(self):
        del self.cluster.nodes[1].cfg['peer_urls']['3']
        job=self.start();self.run_job(job)
        self.assertIsNone(self.cluster.nodes[1].cfg['management_pending'])
        self.assertTrue(self.cluster.nodes[3].cfg['standby_ready'])
    def test_cancel_new_standby_uses_saved_address_before_roles_change(self):
        del self.cluster.nodes[1].cfg['peer_urls']['3']
        job=self.start()
        with patch.object(m,'fresh'):
            result=m.cancel(m.Resume(request_id=job['request_id']),{'login':'owner'},None)
        self.assertTrue(result['ok'])
        self.assertIsNone(self.cluster.nodes[1].cfg['management_pending'])
        self.assertEqual(self.cluster.nodes[1].cfg['standby_post'],2)
    def test_lost_ack_at_each_boundary_resumes_same_operation_without_reset(self):
        for action in ('management-prepare','management-retire','management-activate'):
            with self.subTest(action=action):
                self.cluster=Cluster();job=self.start();self.cluster.drop=action
                self.run_job(job)
                pending=self.cluster.nodes[1].cfg['management_pending']
                self.assertEqual(pending['request_id'],job['request_id']);self.assertTrue(pending['error'])
                self.run_job(job)
                self.assertIsNone(self.cluster.nodes[1].cfg['management_pending'])
                self.assertEqual(self.cluster.nodes[1].cfg['management_last']['request_id'],job['request_id'])
                self.assertEqual(self.cluster.nodes[3].cfg['generation'],4)
                self.assertEqual(self.cluster.nodes[3].proof,PROOF)
    def test_planned_handover_demotes_old_primary_before_target_activation(self):
        job=self.start('handover');self.run_job(job)
        self.assertEqual(m.roles(self.cluster.nodes[1].cfg),{'primary_post':2,'standby_post':1,'generation':4})
        self.assertEqual(m.roles(self.cluster.nodes[2].cfg),job['after'])
        events=self.cluster.events
        self.assertLess(events.index((1,'wallet_role_change_local_committed')),events.index((2,'wallet_role_change_target_activated')))
    def test_handover_requires_current_ready_matching_standby(self):
        self.cluster.nodes[2].proof['state_digest']='c'*64
        with self.assertRaises(WalletConflict):self.start('handover')
        self.assertFalse(self.cluster.events)
    def test_foreign_primary_or_ready_candidate_cannot_be_overwritten(self):
        for key,value in (('standby_ready',True),('primary_post',9)):
            with self.subTest(key=key):
                self.cluster=Cluster();self.cluster.nodes[3].cfg[key]=value
                with self.assertRaises(WalletConflict):self.start()
                self.assertFalse(self.cluster.events)
    def test_fenced_old_standby_stays_excluded_until_installer_rejoins_it(self):
        self.cluster.offline.add(2)
        job=self.start(fenced=True)
        self.run_job(job)
        self.assertEqual(self.cluster.nodes[2].cfg['generation'],3)
        self.assertEqual(self.cluster.nodes[1].cfg['generation'],4)
        self.assertTrue(self.cluster.nodes[1].cfg['management_last']['old_standby_fenced'])
    def test_live_standby_cannot_be_claimed_physically_disconnected(self):
        with self.assertRaises(WalletConflict):self.start(fenced=True)
        self.assertFalse(self.cluster.events)
    def test_unknown_or_wrong_sender_cannot_activate_target(self):
        job=self.start();self.cluster.current=3
        with self.assertRaises(WalletConflict):m.internal('activate',job,self.cluster.nodes[3].configuration(),2)
        self.assertFalse(self.cluster.nodes[3].cfg.get('management_pending'))
    def test_missing_or_empty_digest_cannot_verify_ready(self):
        for key in ('journal_digest','state_digest'):
            left=deepcopy(PROOF);left[key]=None
            self.assertFalse(m.same_proof(left,left))


class ManagementAccessTests(unittest.TestCase):
    def test_repeated_completed_receipt_does_not_start_a_second_change(self):
        request_id=uuid4()
        previous={'request_id':str(request_id),'kind':'replace_standby','target_post':3,'stage':'completed'}
        host=Mock();host.control_lock=threading.RLock();host.configuration.return_value={
            'primary_post':1,'standby_post':3,'generation':4,'management_last':previous}
        value=m.Change(kind='replace_standby',target_post=3,request_id=request_id,
                       expected_authority={'primary_post':1,'standby_post':2,'generation':3})
        gate=threading.Lock()
        with patch.object(m,'api',return_value=host),patch.object(m,'fresh'),patch.object(m,'worker_lock',gate),patch.object(m,'preflight') as preview,patch.object(m.threading,'Thread') as thread:
            self.assertEqual(m.change(value,{'login':'owner'},None)['operation'],previous)
            preview.assert_not_called();thread.assert_not_called();self.assertFalse(gate.locked())
    def test_recovery_requires_physical_flags_and_rejects_a_responding_primary(self):
        from app.wallet_api import PromoteRequest
        from fastapi import HTTPException
        host=Mock();host.configuration.return_value={'local_post':2,'primary_post':1,'standby_post':2,'standby_ready':True}
        host.PromoteRequest=PromoteRequest
        with patch.object(m,'api',return_value=host),patch.object(m,'fresh'),patch.object(m,'idle'),patch.object(m,'remote',return_value={'ok':True}) as remote:
            with self.assertRaises(HTTPException):m.recover(m.Recovery(old_primary_fenced=False,single_copy_accepted=True),{'login':'owner'},None)
            remote.assert_not_called()
            with self.assertRaises(HTTPException):m.recover(m.Recovery(old_primary_fenced=True,single_copy_accepted=True),{'login':'owner'},None)
            host.promote.assert_not_called()
            remote.side_effect=WalletUnavailable('disconnected')
            m.recover(m.Recovery(old_primary_fenced=True,single_copy_accepted=True),{'login':'owner'},None)
            host.promote.assert_called_once()
    def test_role_and_fresh_login_are_required_before_any_change(self):
        app=FastAPI();app.include_router(m.router);client=TestClient(app)
        value={'kind':'handover','target_post':2,'request_id':str(uuid4()),'expected_authority':{'primary_post':1,'standby_post':2,'generation':3}}
        with patch.object(m,'api') as host:
            self.assertEqual(client.post('/api/wallet-management/change',json=value).status_code,401)
            app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
            with patch.object(m,'decode_access_token',return_value={'iat':1}):
                self.assertEqual(client.post('/api/wallet-management/change',json=value,headers={'Authorization':'Bearer old'}).status_code,401)
            host.assert_not_called()
        self.assertEqual(m.Change(**{**value,'request_id':value['request_id']}).target_post,2)
