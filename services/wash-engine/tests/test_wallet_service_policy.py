import unittest
from unittest.mock import MagicMock,patch
from datetime import datetime,UTC
from app.wallet_devices import site_policy
from app.wallet_domain import WalletState,apply_command

class ServicePolicyTests(unittest.TestCase):
 def policy(self,device_policy=None):
  conn=MagicMock();conn.execute.return_value.fetchall.return_value=[{'setting_key':'wash_parameters','setting_value':{'freePauseSeconds':60,'tariffs':{'water':{'amountSum':2000,'durationSeconds':40,'enabled':True}}}},{'setting_key':'dry_fog_parameters','setting_value':{'freePauseSeconds':300,'tariffs':{'aroma_1':{'amountSum':1000,'durationSeconds':1,'enabled':True}}}}]
  manager=MagicMock();manager.__enter__.return_value=conn
  # The authority has only aroma tariffs; it must not supply wash references.
  with patch('app.db.db',return_value=manager),patch('app.wash_logic.wash_runtime.params',{'tariffs':{'aroma_1':{'amountSum':1000,'durationSeconds':1}}}):
   return site_policy({'visit_timeout_minutes':30,'device_policy':device_policy})
 def test_legacy_policy_references_wash_even_on_fog_primary(self):
  p=self.policy();self.assertEqual((p.water_amount_sum,p.water_duration_seconds,p.free_pause_millis),(2000,40,60000));self.assertEqual(p.dry_fog_amount_sum,1000)
 def test_service_pause_overrides_and_null_policy(self):
  self.assertEqual(self.policy({'wash_pause_seconds':90}).free_pause_millis,90000)
  self.assertEqual(self.policy(None).free_pause_millis,60000)
 def test_legacy_cash_return_keeps_money_and_bonus(self):
  policy=self.policy();s=WalletState('TEST');now=datetime(2026,10,21,tzinfo=UTC)
  base={'post_no':2,'assignment_id':'return','visit_id':'visit'}
  for cmd in [dict(action='open_post',amount_sum=15400,bonus_sum=1400,pause_millis=60000),dict(action='checkpoint',remaining_sum=15400,remaining_bonus_sum=1400,pause_millis=60000,funding=[]),dict(action='prepare_return'),dict(action='complete_return')]:
   s,_=apply_command(s,{**base,**cmd},now=now,policy=policy)
  self.assertEqual((s.wallet_sum,s.wallet_bonus_sum),(15400,1400));self.assertIsNone(s.assignment)
 def test_signed_legacy_execute_on_fog_authority_uses_service_references(self):
  import time,json
  from app import wallet_api
  cfg={'enabled':True,'site_id':'TEST','local_post':1,'primary_post':1,'standby_post':2,'generation':1,'single_node':False,'visit_timeout_minutes':30,'peer_urls':{'1':'http://10.0.0.1','2':'http://10.0.0.2'}}
  body={'site_id':'TEST','timestamp':int(time.time()),'sender_post':2,'payload':{'uid':'TEST','operation_id':'same-pending-return','expected_authority':{'primary_post':1,'generation':1},'command':{'action':'open_post','post_no':2,'amount_sum':15400}}}
  secret='test-signature-only';sig=wallet_api.signature(secret,'/api/wallet/internal/execute',body)
  policy=self.policy();manager=MagicMock();executor=MagicMock();executor.execute.return_value={'ok':True,'result':{'amount_sum':15400}}
  with patch.object(wallet_api,'configuration',return_value=cfg),patch.object(wallet_api,'identity',return_value={'site_token':secret}),patch.object(wallet_api,'store_context',return_value=manager),patch.object(wallet_api,'coordinator',return_value=executor),patch('app.wallet_devices.site_policy',return_value=policy),patch('app.wash_logic.wash_runtime.params',{'freePauseSeconds':300,'tariffs':{'aroma_1':{'amountSum':1000,'durationSeconds':1}}}):
   response=wallet_api.internal('execute',body,sig)
  self.assertEqual(response.status_code,200,response.body)
  executor.execute.assert_called_once()
  self.assertEqual(executor.execute.call_args.args[0],'same-pending-return')
  self.assertIs(executor.execute.call_args.args[3],policy)
