import unittest
import pandas as pd
from nar_decision_v3 import validate_snapshot, decide, fit_calibration, walk_forward

class DecisionTests(unittest.TestCase):
    def snapshot(self):
        return pd.DataFrame([dict(race_id='r1',horse_no=i,snapshot_at='2026-10-22T03:00:00Z',cutoff_at='2026-10-22T03:10:00Z',score=i,win_odds=5,place_odds=2,source='official-pre-race') for i in [1,2,3]])
    def test_future_snapshot_rejected(self):
        s=self.snapshot();s.loc[0,'snapshot_at']='2026-10-22T03:11:00Z'
        with self.assertRaises(ValueError):validate_snapshot(s)
    def test_duplicate_rejected(self):
        s=self.snapshot()
        with self.assertRaises(ValueError):validate_snapshot(pd.concat([s,s.iloc[:1]]))
    def test_no_calibration_no_bet(self):
        self.assertTrue(decide(self.snapshot(),None,as_of='2026-10-22T03:05:00Z').empty)
    def test_budget(self):
        m={'edges':[0,3],'rates':[0.5],'training_end':'2026-10-20'}
        self.assertTrue(decide(self.snapshot(),{'win':m},as_of='2026-10-22T03:05:00Z',already_spent=5000).empty)
        self.assertEqual(decide(self.snapshot(),{'win':m},as_of='2026-10-22T03:05:00Z',already_spent=4900).stake_yen.sum(),100)
    def test_no_training_future_leak(self):
        d=pd.DataFrame([dict(race_id=str(i),score=i,won=i%2,race_date=f'2026-01-{i:02d}') for i in range(1,31)])
        m=fit_calibration(d,min_races=30)
        self.assertEqual(m['training_end'],'2026-01-30')
    def test_missing_result_rejected(self):
        with self.assertRaises(ValueError):walk_forward(self.snapshot(),pd.DataFrame())
if __name__=='__main__':unittest.main()
