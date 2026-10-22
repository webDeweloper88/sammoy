import unittest
from unittest.mock import patch
from app.wallet_replication import WalletUnavailable
from app import wallet_registry, customer_registry

class CardsPrimaryGuardTests(unittest.TestCase):
 def test_secondary_vip_and_customer_writes_stop_before_storage(self):
  for local,primary in [(2,1),(3,1),(1,2)]:
   cfg={'enabled':True,'site_id':'TEST','local_post':local,'primary_post':primary,'standby_post':local,'generation':1,'single_node':False}
   for name,args in [('save_profiles',(None,{})),('save_card',(None,{})),('remove_card',('ABC',{}))]:
    with self.subTest(local=local,primary=primary,operation=name),patch.object(wallet_registry,'configuration',return_value=cfg),patch.object(wallet_registry,'store_context') as store:
     with self.assertRaises(WalletUnavailable):getattr(wallet_registry,name)(*args)
     store.assert_not_called()
   with patch.object(customer_registry,'configuration',return_value=cfg),patch.object(customer_registry,'store_context') as store:
    with self.assertRaises(WalletUnavailable):customer_registry.save(None,{})
    store.assert_not_called()
