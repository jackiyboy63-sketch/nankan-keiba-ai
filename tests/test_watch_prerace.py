import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from nar_watch_prerace import tick, discover, reconcile


class WatchTests(unittest.TestCase):
    def state(self):
        return dict(day='2026-10-23', venue='大井', races=[dict(race=1, cutoff_at='2026-10-23T18:00:00+09:00', status='pending', attempts=0)])

    def execute(self, state, when, runner):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            done = tick(state, path, 'history.csv', 'runs', lambda: datetime.fromisoformat(when), runner)
            if path.exists():
                self.assertEqual(json.loads(path.read_text()), state)
            return done

    def test_before_window_no_acquisition(self):
        runner=Mock(); self.assertFalse(self.execute(self.state(), '2026-10-23T17:54:59+09:00', runner));runner.assert_not_called()

    def test_window_once_and_restart(self):
        s=self.state(); runner=Mock(return_value=Path('saved'))
        self.assertTrue(self.execute(s, '2026-10-23T17:55:00+09:00', runner))
        self.execute(s, '2026-10-23T17:56:00+09:00', runner);self.assertEqual(runner.call_count,1)

    def test_late_marked_missed(self):
        s=self.state(); runner=Mock();self.assertTrue(self.execute(s, '2026-10-23T17:59:00+09:00', runner))
        self.assertEqual(s['races'][0]['status'],'missed');runner.assert_not_called()

    def test_retry_bounded_and_spaced(self):
        s=self.state();runner=Mock(side_effect=ValueError('network'))
        for minute in ['55:00','55:30','56:00','57:00','58:00']:
            self.execute(s, '2026-10-23T17:'+minute+'+09:00', runner)
        self.assertEqual(runner.call_count,3);self.assertEqual(s['races'][0]['status'],'failed')

    def test_date_rollover_stops(self):
        with self.assertRaisesRegex(ValueError,'day changed'):
            self.execute(self.state(),'2026-10-24T10:00:00+09:00',Mock())

    def test_refresh_time_between_races(self):
        s=self.state();s['races'].append(dict(s['races'][0],race=2));runner=Mock(return_value='saved')
        times=iter([datetime.fromisoformat('2026-10-23T17:'+m+'+09:00') for m in ['55:00','55:00','59:00']])
        with tempfile.TemporaryDirectory() as tmp:
            tick(s,Path(tmp)/'s.json','h','out',lambda:next(times),runner)
        self.assertEqual(runner.call_count,1);self.assertEqual(s['races'][1]['status'],'missed')

    def test_discovery_errors_are_explicit(self):
        s=discover('2026-10-23','大井',Mock(side_effect=ValueError('unavailable')),lambda _:None)
        self.assertEqual(len(s['discovery_errors']),12);self.assertEqual(s['races'],[])

    def test_recover_completed_after_interruption(self):
        from unittest.mock import patch
        s=self.state()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'2026-10-23/20-01/saved';p.mkdir(parents=True);(p/'run_manifest.json').write_text('{}')
            with patch('nar_watch_prerace.read_run',return_value=({'race_id':'2026-10-23_20_01'},{})):
                reconcile(s,tmp)
        self.assertEqual(s['races'][0]['status'],'completed')
