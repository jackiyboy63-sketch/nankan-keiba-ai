import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from nar_cloud_prerace import session


class CloudTests(unittest.TestCase):
    def execute(self, discovery, ticker, mono=lambda:0, pause=lambda _:None):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'h.csv').write_text('fixture')
            return session(root/'h.csv',root/'runs',root/'state',1,
                clock=lambda:datetime.fromisoformat('2026-10-26T14:00:00+09:00'),
                monotonic=mono,pause=pause,discoverer=discovery,ticker=ticker)

    def discovery(self,day,venue):
        return dict(day=day,venue=venue,races=[dict(race=1,status='pending')],discovery_errors=[])

    def test_all_venues_discovered_and_processed(self):
        d=Mock(side_effect=self.discovery);tick=Mock(return_value=True)
        s=self.execute(d,tick);self.assertEqual(d.call_count,4);self.assertEqual(tick.call_count,4)
        self.assertEqual(s['reason'],'all_verified_races_terminal')

    def test_unknown_schedule_is_reported(self):
        d=lambda day,venue:dict(day=day,venue=venue,races=[],discovery_errors=[{'reason':'unavailable'}])
        s=self.execute(d,Mock());self.assertEqual(len(s['unverified_venues']),4)

    def test_deadline_preserves_pending(self):
        values=iter([0,0,0,0,0,61])
        s=self.execute(self.discovery,Mock(),lambda:next(values))
        self.assertEqual(s['reason'],'session_deadline');self.assertEqual(len(s['pending_races']),4)

    def test_invalid_duration_before_network(self):
        d=Mock()
        with self.assertRaises(ValueError):session(minutes=346,discoverer=d)
        d.assert_not_called()
