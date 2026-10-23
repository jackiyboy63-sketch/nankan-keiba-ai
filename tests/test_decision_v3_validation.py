import unittest
import pandas as pd
from nar_decision_v3 import validate_snapshot, walk_forward, decide

class ValidationTests(unittest.TestCase):
    def snapshot(self):
        return pd.DataFrame([dict(race_id='r1',horse_no=i,snapshot_at='2026-10-22T03:00:00Z',cutoff_at='2026-10-22T03:10:00Z',score=i,win_odds=5,place_odds=2,source='archive') for i in [1,2,3]])
    def results(self):
        return pd.DataFrame([dict(race_id='r1',horse_no=i,race_date='2026-10-22',won=int(i==1),placed=1,win_return_100=500 if i==1 else 0,place_return_100=200) for i in [1,2,3]])
    def test_partial_results_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing runner'):
            walk_forward(self.snapshot(),self.results().iloc[:2])
    def test_null_source_rejected(self):
        s=self.snapshot();s.loc[0,'source']=None
        with self.assertRaisesRegex(ValueError,'source'):validate_snapshot(s)
    def test_payout_label_conflict_rejected(self):
        r=self.results();r.loc[1,'win_return_100']=100
        with self.assertRaisesRegex(ValueError,'mismatch'):walk_forward(self.snapshot(),r)
    def test_japan_date_rejected(self):
        r=self.results();r['race_date']='2026-10-21'
        with self.assertRaisesRegex(ValueError,'Japan'):walk_forward(self.snapshot(),r)
    def test_negative_stake_rejected(self):
        with self.assertRaisesRegex(ValueError,'stake'):
            decide(self.snapshot(),None,as_of='2026-10-22T03:01:00Z',stake=-100)
    def test_nonfinite_payout_rejected(self):
        r=self.results();r['win_return_100']=r.win_return_100.astype(float);r.loc[0,'win_return_100']=float('inf')
        with self.assertRaisesRegex(ValueError,'payout'):walk_forward(self.snapshot(),r)

    def test_daily_cap_uses_decision_time_not_race_id(self):
        frames=[];results=[]
        for race,day,hour in [('train','2026-10-21','03'),('z_early','2026-10-22','03'),('a_late','2026-10-22','04')]:
            s=self.snapshot();s['race_id']=race;s['snapshot_at']=day+'T'+hour+':00:00Z';s['cutoff_at']=day+'T'+hour+':10:00Z'
            r=self.results();r['race_id']=race;r['race_date']=day
            frames.append(s);results.append(r)
        bets,_=walk_forward(pd.concat(frames),pd.concat(results),min_train_races=1,daily_cap=100)
        self.assertEqual(bets.race_id.tolist(),['z_early'])
