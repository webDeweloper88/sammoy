import unittest
from unittest.mock import Mock
from app.wash_logic import WashRuntime
class RfidDiagnosticsTests(unittest.TestCase):
    def test_rejection_result_survives_reader_heartbeat(self):
        r=WashRuntime()
        r._apply_rfid_card_locked=Mock(side_effect=lambda uid,event:r.state.update(lastRfidStatus='card_rejected'))
        r._process_rfid_events_locked({'rfid':{'online':True},'events':[{'seq':1,'uid':'TEST','time':'2026-10-03T00:00:00Z'}]})
        r._process_rfid_events_locked({'rfid':{'online':True},'events':[]})
        self.assertEqual(r.state['lastRfidStatus'],'online')
        self.assertEqual(r.state['lastRfidResult'],'card_rejected')
        self.assertEqual(r.state['lastRfidProcessedAt'],'2026-10-03T00:00:00Z')
        self.assertEqual(r.state['creditSum'],0)
