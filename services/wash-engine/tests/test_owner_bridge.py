"""Owner API regressions, isolated from hardware and the live database."""
import asyncio
from contextlib import contextmanager
from unittest.mock import patch
import unittest
from fastapi import HTTPException
from app import main
from app.schema import RfidCardRequest

class Result:
    def __init__(self,row=None,rows=None): self.row=row;self.rows=rows or []
    def fetchone(self):return self.row
    def fetchall(self):return self.rows
class FakeConnection:
    def __init__(self):self.queries=[];self.committed=False
    def execute(self,sql,args=None):
        self.queries.append((sql,args))
        if 'SELECT id FROM vip_profiles' in sql:return Result({'id':1})
        return Result()
    def commit(self):self.committed=True
class OwnerTests(unittest.TestCase):
    def test_inactive_cards_can_be_listed(self):
        conn=FakeConnection()
        @contextmanager
        def db():yield conn
        with patch.object(main,'db',db):
            self.assertEqual(main.owner_rfid_cards({'login':'owner'},True)['cards'],[])
        self.assertEqual(conn.queries[0][1],(True,))
        self.assertIn('OR (c.enabled = true',conn.queries[0][0])
    def test_card_with_credit_is_not_converted(self):
        conn=FakeConnection()
        @contextmanager
        def db():yield conn
        with patch.object(main,'db',db):
            with self.assertRaises(HTTPException) as caught:
                main.owner_save_rfid_card(RfidCardRequest(uid='12345678',card_type='vip',vip_profile_id=1),{'login':'owner'})
        self.assertEqual(caught.exception.status_code,409)
        self.assertIn('WHERE rfid_cards.balance_sum = 0',conn.queries[-1][0])
        self.assertFalse(conn.committed)
    def test_report_key_matches_legacy(self):
        calls=[]
        async def request(*args):calls.append(args);return {'ok':True}
        with patch.object(main,'get_license_settings',return_value={'site_code':'SITE','site_token':'secret','post_no':2}),patch.object(main,'telegram_setup_request',request):
            asyncio.run(main.sync_telegram_identity())
        import hashlib
        self.assertEqual(calls[0][2]['api_key'],hashlib.sha256(b'rtu-wash-local-reports-v1:secret').hexdigest())
        self.assertEqual(calls[0][2]['post_no'],2)
