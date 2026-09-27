import tempfile
import unittest
from pathlib import Path
from backend.rhythm import validate
from backend.server import Application

class RhythmTests(unittest.TestCase):
    def test_missing_and_zero_are_distinct(self):
        _, item=validate({'date':'2026-09-27','sleep_hours':0,'mood':0})
        self.assertEqual(item['sleep_hours'],0)
        self.assertIsNone(item['energy'])
        self.assertEqual(item['mood'],0)

    def test_invalid_values_rejected(self):
        for fields in ({'date':'2026-02-30'},{'sleep_hours':float('nan')},
                       {'sleep_hours':25},{'sleep_hours':True},{'mood':3},
                       {'mood':True},{'sleep_start':'24:00'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                validate({'date':'2026-09-27',**fields})

    def test_client_cannot_claim_device_measurement(self):
        _, item=validate({'date':'2026-09-27','mood':1,'source':'device','speech_rate':250})
        self.assertEqual(item['source'],'self_report')
        self.assertNotIn('speech_rate',item)

    def test_save_reload_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'rhythm.sqlite3'
            app=Application(db)
            app.post('/api/rhythm',{'date':'2026-09-27','sleep_hours':7.5,'mood':0})
            app.post('/api/rhythm',{'date':'2026-09-26','sleep_hours':6})
            again=Application(db)
            self.assertEqual(again.state()['rhythm_days']['2026-09-27']['sleep_hours'],7.5)
            again.post('/api/rhythm',{'date':'2026-09-27'})
            self.assertNotIn('2026-09-27',again.state()['rhythm_days'])
            self.assertIn('2026-09-26',again.state()['rhythm_days'])
