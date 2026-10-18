import unittest
from unittest.mock import patch,MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import contact_api as api
from app.auth import current_user
class ContactTests(unittest.TestCase):
 def setUp(self):
  self.app=FastAPI();self.app.include_router(api.router);self.client=TestClient(self.app)
 def test_unauthenticated_cannot_change_settings(self):
  self.assertIn(self.client.post('/api/owner/operator/settings',json={'enabled':True}).status_code,[401,403])
  self.assertIn(self.client.post('/api/admin/manufacturer/settings',json={}).status_code,[401,403])
 def test_owner_cannot_change_manufacturer(self):
  self.app.dependency_overrides[current_user]=lambda:{'role':'owner','must_change_password':False}
  self.assertEqual(self.client.post('/api/admin/manufacturer/settings',json={}).status_code,403)
 def test_chat_id_is_not_public(self):
  with patch.object(api,'read',side_effect=[{'enabled':True,'phone':'+998 90 123 45 67','chat_id':'-100123'},{}]):
   self.assertNotIn('chat_id',str(api.public_contacts()))
 def test_operator_disabled_does_not_contact_telegram(self):
  with patch.object(api,'read',return_value={'enabled':False}),patch.object(api,'dispatch') as send:
   self.assertEqual(self.client.post('/api/kiosk/operator/call',json={'request_id':'11111111-1111-4111-8111-111111111111'}).status_code,409);send.assert_not_called()
 def test_bad_recipient_rejected(self):
  with self.assertRaises(ValueError):api.OperatorSettings(chat_id='https://example.com')
 def test_secondary_routes_to_primary(self):
  from app import wallet_api
  with patch.object(wallet_api,'configuration',return_value={'enabled':True,'local_post':2,'primary_post':1}),patch.object(wallet_api,'rpc',return_value={'status':'queued'}) as send:
   self.assertEqual(api.dispatch({'request_id':'id'})['status'],'queued');self.assertEqual(send.call_args.args[1:3],(1,'operator-call'))

 def test_admin_can_read_manufacturer_settings(self):
  self.app.dependency_overrides[current_user]=lambda:{'role':'admin','must_change_password':False}
  with patch.object(api,'read',return_value={'marketing':'+998 91 111 69 29'}) as read:
   response=self.client.get('/api/admin/manufacturer/settings')
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.json()['settings']['marketing'],'+998 91 111 69 29')
   read.assert_called_once_with('manufacturer_contacts',api.ManufacturerSettings)
