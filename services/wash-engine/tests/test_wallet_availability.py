import unittest
from copy import deepcopy
from datetime import UTC,datetime
from unittest.mock import Mock,patch
from app.wallet_availability import observe
from app.wallet_replication import WalletUnavailable
from app import wallet_api

class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'enabled':True,'primary_post':1,'standby_post':2,'local_post':1,'generation':3,'standby_ready':True,'single_node':False}
        self.proof={'primary_post':1,'standby_post':2,'local_post':2,'generation':3}
    def test_old_ready_flag_never_masks_unavailable_peer_or_changes_configuration(self):
        before=deepcopy(self.cfg)
        remote=Mock(side_effect=WalletUnavailable('Peer response authentication failed'))
        result=observe(self.cfg,remote)
        self.assertEqual(result['nodes'],[{'post':1,'state':'available','reason':None},{'post':2,'state':'unavailable','reason':'authentication_failed'}])
        remote.assert_called_once_with(2);self.assertEqual(self.cfg,before)
    def test_valid_peer_is_available_but_no_journal_claim_is_made(self):
        result=observe(self.cfg,lambda post:self.proof)
        self.assertEqual(result['nodes'][1]['state'],'available');self.assertNotIn('in_sync',result)
        self.assertNotIn('proof',result['nodes'][1])
    def test_wrong_authority_and_identity_are_not_available(self):
        for proof in ({**self.proof,'generation':4},{**self.proof,'local_post':9},{**self.proof,'generation':True}):
            result=observe(self.cfg,lambda post:proof)
            self.assertNotEqual(result['nodes'][1]['state'],'available')
    def test_backup_checks_primary_without_loopback_and_disabled_wallet_does_not_probe(self):
        self.cfg['local_post']=2
        remote=Mock(return_value={**self.proof,'local_post':1})
        self.assertEqual(observe(self.cfg,remote)['nodes'][1]['state'],'available');remote.assert_called_once_with(1)
        self.cfg['enabled']=False;remote.reset_mock();self.assertEqual(observe(self.cfg,remote)['nodes'],[]);remote.assert_not_called()
    def test_history_is_only_read_from_successful_sync_events(self):
        stamp=datetime(2026,10,20,10,0,tzinfo=UTC)
        with patch.object(wallet_api,'db') as db:
            connection=db.return_value.__enter__.return_value
            connection.execute.return_value.fetchone.return_value={'synced_at':stamp}
            self.assertEqual(wallet_api.last_sync_at(self.cfg),stamp.isoformat())
            query,params=connection.execute.call_args.args
            self.assertTrue(query.lstrip().startswith('SELECT'));self.assertIn('wallet_replication_restored',query);self.assertNotIn('wallet_proof_failed',query)
            self.assertEqual(params[0].obj,{'primary':1,'standby':2,'generation':3})
            connection.commit.assert_not_called()
    def test_availability_endpoint_uses_only_signed_read_only_status(self):
        with patch.object(wallet_api,'configuration',return_value=self.cfg),patch.object(wallet_api,'rpc',return_value=self.proof) as rpc:
            wallet_api.owner_availability({'login':'owner'})
            rpc.assert_called_once_with(self.cfg,2,'status',{})
