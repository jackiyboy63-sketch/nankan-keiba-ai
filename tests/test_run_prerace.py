import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import test_prerace_rating as fixtures
from nar_run_prerace import run

class PipelineTests(unittest.TestCase):
    def execute(self,tmp,clock_time='2026-10-23T17:00:30+09:00',age=180):
        root=Path(tmp);helper=fixtures.PreraceRatingTests();helper.history().to_csv(root/'history.csv',index=False)
        entries=helper.entries();entries['win_odds']=5.;entries['place_odds_low']=1.2;entries['place_odds_high']=2.3
        def capture(day,venue,race,output):
            p=Path(output)/'fixture';p.mkdir(parents=True);(p/'manifest.json').write_text('{}');return p
        m={'cutoff_at':'2026-10-23T18:00:00+09:00','snapshot_at':'2026-10-23T17:00:00+09:00','race_id':'2026-10-23_20_01'}
        with patch('nar_run_prerace.capture',side_effect=capture),patch('nar_run_prerace.verify_capture',return_value=(entries,1600,'良',m)):
            return run('大井',1,root/'history.csv',root/'runs',age,clock=lambda:pd.Timestamp(clock_time))
    def test_completed_outputs_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self.execute(tmp);m=json.loads((folder/'run_manifest.json').read_text());self.assertEqual(m['status'],'completed_prerace');self.assertIn('scored_snapshot.csv',m['files'])
            s=pd.read_csv(folder/'scored_snapshot.csv');self.assertEqual(s.iloc[0].place_odds_high,2.3);self.assertNotIn('place_odds',s.columns)
    def test_after_start_fails_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'before'):self.execute(tmp,'2026-10-23T18:00:00+09:00',600)
            m=json.loads(next(Path(tmp).rglob('run_manifest.json')).read_text());self.assertEqual(m['status'],'failed')
    def test_stale_odds_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'old'):self.execute(tmp,'2026-10-23T17:04:00+09:00')
    def test_clock_before_source_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'ordering'):self.execute(tmp,'2026-10-23T16:59:59+09:00')
    def test_missing_history_before_network(self):
        with patch('nar_run_prerace.capture') as collect:
            with self.assertRaisesRegex(ValueError,'history'):run('大井',1,'/does/not/exist')
            collect.assert_not_called()
