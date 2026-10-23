from copy import deepcopy
import unittest
from unittest.mock import patch,Mock
from fastapi import HTTPException
from app import software_updates as u

class UpdateQueueTests(unittest.TestCase):
    def setUp(self):
        self.c={'enabled':True,'local_post':1,'primary_post':1,'standby_post':2,'generation':7,'peer_urls':{'1':'http://10.0.0.1','2':'http://10.0.0.2','3':'http://10.0.0.3'}}
        self.q={'id':'q','status':'running','primary_post':1,'generation':7,'release_no':1,'envelope':{},'posts':[{'post_no':p,'id':str(p),'status':'waiting'} for p in (1,2,3)]}
        self.calls=[]
        self.info={'ok':True,'trusted_key_configured':True,'ready':True,'installed':{'release_no':0}}
    def tick(self,call):
        with patch.object(u,'cfg',return_value=self.c),patch.object(u,'read_queue',return_value=self.q),patch.object(u,'save_queue') as save,patch.object(u,'peer',side_effect=call):u.tick()
        return save
    def normal(self,c,p,body):
        self.calls.append((p,body['action']))
        return deepcopy(self.info) if body['action']=='status' else {'status':'queued'}
    def test_ordinary_post_precedes_wallet_nodes(self):
        self.tick(self.normal);self.assertIn((3,'install'),self.calls);self.assertNotIn((1,'install'),self.calls)
    def test_busy_and_offline_nodes_never_allow_primary_to_jump_queue(self):
        def call(c,p,body):
            self.calls.append((p,body['action']))
            if p==3:raise RuntimeError('offline')
            return {**self.info,'ready':False}
        self.tick(call);self.assertFalse(any(action=='install' for p,action in self.calls))
    def test_offline_ordinary_node_does_not_block_ready_standby(self):
        def call(c,p,body):
            if p==3:raise RuntimeError('offline')
            return self.normal(c,p,body)
        self.tick(call);self.assertIn((2,'install'),self.calls);self.assertNotIn((1,'install'),self.calls)
    def test_lost_ack_is_resolved_by_receipt_without_resubmit(self):
        self.q['posts'][2]['status']='installing'
        self.tick(lambda c,p,b:{'status':'completed'})
        self.assertEqual(self.q['posts'][2]['status'],'completed')
    def test_definite_missing_receipt_retries_same_uuid(self):
        self.q['posts'][2]['status']='installing'
        def missing(c,p,b):raise HTTPException(409,'job_not_found')
        self.tick(missing);self.assertEqual(self.q['posts'][2]['status'],'waiting');self.assertEqual(self.q['posts'][2]['id'],'3')
    def test_role_change_stops_queue(self):
        self.c['generation']=8;self.tick(self.normal)
        self.assertEqual(self.q['status'],'needs_review');self.assertEqual(self.calls,[])
    def test_nonprimary_internal_cannot_trigger_install(self):
        with patch.object(u,'agent') as agent,self.assertRaises(HTTPException):u.internal({'action':'install','generation':7},self.c,3)
        agent.assert_not_called()
    def test_primary_restarts_then_completes_own_persisted_receipt(self):
        for p in self.q['posts']:p['status']='completed' if p['post_no']!=1 else 'installing'
        self.tick(lambda c,p,b:{'status':'completed'});self.tick(self.normal)
        self.assertEqual(self.q['status'],'completed')

class MaintenanceInterlockTests(unittest.TestCase):
    def test_expired_interlock_releases_without_money_mutation(self):
        from app.software_maintenance import blocked
        runtime=Mock();runtime.state={'creditSum':1234,'softwareUpdateJob':'job','softwareUpdatePendingUntil':1}
        with patch('app.software_maintenance.time.monotonic',return_value=2):self.assertFalse(blocked(runtime))
        self.assertEqual(runtime.state,{'creditSum':1234})
    def test_interlock_blocks_card_before_wallet(self):
        from app.wash_logic import WashRuntime
        runtime=WashRuntime();runtime.state.update(softwareUpdatePendingUntil=100,softwareUpdateJob='job')
        with patch('app.software_maintenance.time.monotonic',return_value=1),patch('app.wallet_post.freeze') as freeze:
            runtime._apply_rfid_card_locked('01020304',{'sak':8,'atqa':'0400'})
        freeze.assert_not_called();self.assertEqual(runtime.state['lastRfidStatus'],'software_update_pending')
    def test_maintenance_cannot_be_acquired_with_a_pending_click_payment(self):
        from app.wash_logic import WashRuntime
        from uuid import uuid4
        runtime=WashRuntime();runtime.state['outputsOffConfirmed']=True
        with patch('app.wash_logic.wash_runtime',runtime),patch('pathlib.Path.read_text',return_value='local-secret'),patch.object(u,'db') as database:
            database.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'n':1}
            with self.assertRaises(HTTPException):u.maintenance_lease('prepare',u.Lease(id=uuid4()),'local-secret')
        self.assertNotIn('softwareUpdateJob',runtime.state)
