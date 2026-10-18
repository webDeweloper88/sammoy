import unittest
from app.kiosk_defaults import normalize_kiosk_settings
class KioskAppearanceTests(unittest.TestCase):
 def test_existing_install_gets_auto_schedule(self):
  c=normalize_kiosk_settings({'brand':{'name':'Existing'},'programs':[]})
  self.assertEqual(c['theme']['appearance'],{'mode':'auto','manualTheme':'dark','lightStart':'08:00','lightEnd':'18:00','timezone':'Asia/Tashkent'})
  self.assertEqual(c['brand']['name'],'Existing')
 def test_manual_and_schedule_survive_round_trip(self):
  a={'mode':'manual','manualTheme':'light','lightStart':'22:30','lightEnd':'06:45','timezone':'Asia/Tashkent'}
  c=normalize_kiosk_settings({'theme':{'appearance':a}})
  self.assertEqual(normalize_kiosk_settings(c)['theme']['appearance'],a)
 def test_design_is_independent_and_survives_normalization(self):
  for design in ["wheel","cards"]:
   c=normalize_kiosk_settings({"theme":{"design":design,"appearance":{"mode":"manual","manualTheme":"light"}}})
   self.assertEqual(normalize_kiosk_settings(c)["theme"]["design"],design)
   self.assertEqual(c["theme"]["appearance"]["manualTheme"],"light")
  self.assertEqual(normalize_kiosk_settings({"theme":{"design":"invalid"}})["theme"]["design"],"wheel")
 def test_invalid_appearance_falls_back_safely(self):
  c=normalize_kiosk_settings({'theme':{'appearance':{'mode':{},'manualTheme':[],'lightStart':'25:99','lightEnd':None,'timezone':'Europe/London'}}})
  self.assertEqual(c['theme']['appearance']['mode'],'auto')
  self.assertEqual(c['theme']['appearance']['lightStart'],'08:00')
  self.assertEqual(c['theme']['appearance']['lightEnd'],'18:00')
  self.assertEqual(c['theme']['appearance']['timezone'],'Asia/Tashkent')

class ImmediateAppearanceTests(unittest.TestCase):
 def test_only_appearance_is_updated(self):
  from unittest.mock import MagicMock,patch
  from app.main import save_kiosk_appearance,KioskSettingsRequest
  c=normalize_kiosk_settings({'brand':{'name':'Keep brand'},'payment':{'quickAmounts':[5000]},'theme':{'appearance':{'lightStart':'09:30','lightEnd':'19:00'}}})
  conn=MagicMock();conn.execute.return_value.fetchone.return_value={'setting_value':c}
  manager=MagicMock();manager.__enter__.return_value=conn
  with patch('app.main.db',return_value=manager):
   result=save_kiosk_appearance(KioskSettingsRequest(config={'mode':'light'}),{'login':'owner'})
  self.assertEqual(result['appearance']['mode'],'manual')
  self.assertEqual(result['appearance']['manualTheme'],'light')
  saved=conn.execute.call_args.args[1][0].obj
  self.assertEqual(saved['brand']['name'],'Keep brand')
  self.assertEqual(saved['theme']['appearance']['lightStart'],'09:30')
  self.assertEqual(saved['payment']['quickAmounts'],[5000])
  conn.commit.assert_called_once()
 def test_invalid_choice_rejected(self):
  from fastapi import HTTPException
  from app.main import save_kiosk_appearance,KioskSettingsRequest
  with self.assertRaises(HTTPException):save_kiosk_appearance(KioskSettingsRequest(config={'mode':'invalid'}),{'login':'owner'})
 def test_only_owner_can_change_appearance(self):
  from fastapi.testclient import TestClient
  from app.main import app
  from app.auth import current_user
  client=TestClient(app)
  self.assertEqual(client.post('/api/owner/kiosk/appearance',json={'config':{'mode':'light'}}).status_code,401)
  app.dependency_overrides[current_user]=lambda:{'role':'admin','must_change_password':False}
  try:self.assertEqual(client.post('/api/owner/kiosk/appearance',json={'config':{'mode':'light'}}).status_code,403)
  finally:app.dependency_overrides.clear()

class FooterIdentityTests(unittest.TestCase):
 def test_public_identity_uses_configured_post_only(self):
  from unittest.mock import MagicMock,patch
  from app.main import get_kiosk_settings
  conn=MagicMock();conn.execute.return_value.fetchone.return_value=None
  manager=MagicMock();manager.__enter__.return_value=conn
  with patch('app.main.db',return_value=manager),patch('app.main.get_license_settings',return_value={'site_code':'SITE','post_no':3,'site_token':'private'}):
   data=get_kiosk_settings()
  self.assertEqual(data['station'],{'postNo':3})
  self.assertNotIn('site_token',data['station'])
  with patch('app.main.db',return_value=manager),patch('app.main.get_license_settings',return_value={'site_code':'','post_no':1}):
   self.assertIsNone(get_kiosk_settings()['station']['postNo'])
 def test_footer_contacts_survive_normalization(self):
  c=normalize_kiosk_settings({'contacts':{'supportPhone':'+998 91 123 45 67','socialLinks':{'telegram':'https://t.me/fixture'}}})
  self.assertEqual(c['contacts']['supportPhone'],'+998 91 123 45 67')
  self.assertEqual(c['contacts']['socialLinks']['telegram'],'https://t.me/fixture')
  self.assertEqual(c['contacts']['socialLinks']['youtube'],'')
