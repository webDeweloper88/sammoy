import threading,unittest
from uuid import uuid4
from unittest.mock import Mock,patch
from fastapi import HTTPException
from app import admin_api as api
class AdminCreditTests(unittest.TestCase):
 def payload(self,**change):
  return api.TestCreditRequest(**{'amount_sum':10000,'operation_id':uuid4(),'reason':'NFC acceptance test','confirmation':'TEST CREDIT 10000',**change})
 def execute(self,payload,previous=None,state=None):
  runtime=Mock(lock=threading.RLock());runtime.snapshot.return_value={'state':{'creditSum':0,'lastIoOk':True,**(state or {})}};runtime.add_credit.return_value={'state':{'creditSum':10000}}
  database=Mock();database.__enter__=Mock(return_value=database);database.__exit__=Mock(return_value=False);database.execute.return_value.fetchone.return_value=previous
  with patch.object(api,'wash_runtime',runtime),patch.object(api,'db',return_value=database),patch.object(api,'audit'):
   result=api.test_credit(payload,{'id':1,'login':'admin'})
  return result,runtime
 def test_exact_admin_amount_has_no_bonus_and_records_actor(self):
  result,runtime=self.execute(self.payload());self.assertFalse(result['already_applied'])
  self.assertEqual(runtime.add_credit.call_args.args,(10000,'admin'));self.assertEqual(runtime.add_credit.call_args.kwargs['bonus_sum'],0)
  self.assertTrue(runtime.add_credit.call_args.kwargs['raw_payload']['test_credit'])
 def test_retry_after_money_has_been_spent_never_credits_again(self):
  payload=self.payload();previous={'provider':'admin','amount_sum':10000,'raw_payload':{'reason':payload.reason,'changed_by':'admin','test_credit':True}}
  result,runtime=self.execute(payload,previous,{'creditSum':0});self.assertTrue(result['already_applied']);runtime.add_credit.assert_not_called()
 def test_reused_id_with_different_amount_rejected(self):
  with self.assertRaises(HTTPException):self.execute(self.payload(),{'provider':'admin','amount_sum':20000,'raw_payload':{}})
 def test_customer_session_or_fault_cannot_receive_test_credit(self):
  for state in [{'creditSum':1},{'activeSessionId':1},{'armedMode':'water'},{'lastIoOk':False},{'licenseLocked':True}]:
   with self.subTest(state=state),self.assertRaises(HTTPException):self.execute(self.payload(),state=state)
 def test_confirmation_required(self):
  with self.assertRaises(HTTPException):self.execute(self.payload(confirmation=''))
