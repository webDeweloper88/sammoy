import unittest
from app.wallet_diagnostics import compare,observe
from app.wallet_replication import WalletUnavailable

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'enabled':True,'site_id':'SITE','local_post':1,'primary_post':1,'standby_post':7,'generation':2,'single_node':False}
        self.proof={'proof_version':2,'local_post':1,'primary_post':1,'standby_post':7,'generation':2,'journal_digest':'a'*64,'state_digest':'b'*64,'operation_count':10,'pending_count':0}
    def nodes(self,**change):return [{'online':True,'proof':self.proof},{'online':True,'proof':{**self.proof,'local_post':7,**change}}]
    def test_only_complete_matching_evidence_reports_in_sync(self):
        self.assertEqual(compare(self.cfg,self.nodes()),'in-sync')
        for change,state in [({'generation':3},'authority-mismatch'),({'proof_version':1},'protocol-mismatch'),({'pending_count':1},'pending'),({'state_digest':'c'*64},'differs'),({'journal_digest':'d'*64},'differs'),({'operation_count':11},'differs'),({'pending_count':None},'protocol-mismatch')]:
            with self.subTest(change=change):self.assertEqual(compare(self.cfg,self.nodes(**change)),state)
    def test_missing_digest_never_reports_in_sync(self):
        self.proof.pop('state_digest');self.assertEqual(compare(self.cfg,self.nodes()),'protocol-mismatch')
    def test_offline_wrong_peer_and_single_copy_are_explicit(self):
        def offline(post):raise WalletUnavailable('unavailable')
        result=observe(self.cfg,lambda:self.proof,offline)
        self.assertEqual(result['state'],'unavailable');self.assertFalse(result['nodes'][1]['online'])
        result=observe(self.cfg,lambda:self.proof,lambda post:self.proof)
        self.assertEqual(result['state'],'unavailable')
        self.cfg['single_node']=True;self.assertEqual(observe(self.cfg,lambda:self.proof,offline)['state'],'single-copy')
    def test_disabled_mode_never_contacts_peers(self):
        from unittest.mock import Mock
        self.cfg['enabled']=False;local=Mock();remote=Mock()
        self.assertEqual(observe(self.cfg,local,remote)['state'],'not-configured');local.assert_not_called();remote.assert_not_called()
