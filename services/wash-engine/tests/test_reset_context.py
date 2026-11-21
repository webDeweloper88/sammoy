import unittest
from app.reset_context import classify

class ResetContextTests(unittest.TestCase):
    def test_fresh_or_disabled_defaults_are_standalone(self):
        for cfg in ({},{'enabled':False,'primary_post':1,'standby_post':None,'peer_urls':{}}):
            r=classify(1,cfg,[],False)
            self.assertEqual(r['role'],'standalone');self.assertFalse(r['requires_confirmation'])
    def test_each_shared_role(self):
        cfg={'enabled':True,'primary_post':1,'standby_post':2}
        for post,role,isolation in ((1,'primary',True),(2,'standby',True),(3,'member',False)):
            r=classify(post,cfg,[],False)
            self.assertEqual(r['role'],role);self.assertTrue(r['requires_confirmation']);self.assertEqual(r['requires_peer_isolation'],isolation)
    def test_disabling_wallet_cannot_hide_prior_authority(self):
        for post,role in ((1,'primary'),(2,'standby')):
            r=classify(post,{'enabled':False},[{'primary':1,'standby':2}],True)
            self.assertEqual(r['role'],role);self.assertTrue(r['requires_peer_isolation'])
    def test_historical_primary_remains_conservative_after_role_change(self):
        r=classify(3,{'enabled':True,'primary_post':1,'standby_post':2},[{'primary':3,'standby':2}],True)
        self.assertEqual(r['role'],'primary')
    def test_orphan_data_does_not_invent_a_primary_from_default_settings(self):
        r=classify(1,{'enabled':False,'primary_post':1},[],True)
        self.assertEqual(r['role'],'previous_member');self.assertTrue(r['requires_peer_isolation'])
    def test_context_changes_on_role_or_history_changes(self):
        a=classify(3,{'enabled':True,'primary_post':1,'standby_post':2},[],True)
        b=classify(3,{'enabled':True,'primary_post':3,'standby_post':2},[],True)
        self.assertNotEqual(a['context_id'],b['context_id'])
        self.assertEqual(a,classify(3,{'enabled':True,'primary_post':1,'standby_post':2},[],True))

    def test_repeated_audit_events_do_not_invalidate_same_role_confirmation(self):
        cfg={'enabled':True,'primary_post':1,'standby_post':2}
        a=classify(1,cfg,[{'primary':1,'standby':2}],True)
        b=classify(1,cfg,[{'primary':1,'standby':2}]*2,True)
        self.assertEqual(a['context_id'],b['context_id'])
