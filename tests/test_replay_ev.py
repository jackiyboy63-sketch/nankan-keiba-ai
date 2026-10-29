import unittest
import numpy as np,pandas as pd
from nar_replay_ev import make_frame,validate_odds
class ReplayTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame([dict(race_date='2026-10-27',race_key='old',horse_key='h'+str(i),馬番=i,着順=i,頭数=2,距離=1400,タイム=1300+i,競馬場='大井',**{'上がり3F':38+i}) for i in [1,2]])
    def entries(self):return pd.DataFrame({'馬番':[1,2],'horse_key':['h1','h2']})
    def test_future_rows_ignored(self):
        h=self.history();other=h.copy();other.race_date='2026-10-30';other.race_key='future';other['着順']=[2,1]
        a=make_frame(h,self.entries(),'2026-10-28','大井',1600,'target')
        b=make_frame(pd.concat([h,other]),self.entries(),'2026-10-28','大井',1600,'target')
        pd.testing.assert_frame_equal(a,b)
    def test_no_history_rejects_entire_race(self):
        e=self.entries();e.loc[0,'horse_key']='new'
        with self.assertRaisesRegex(ValueError,'全馬'):make_frame(self.history(),e,'2026-10-28','大井',1600,'target')
    def test_target_distance_used(self):
        f=make_frame(self.history(),self.entries(),'2026-10-28','大井',1600,'target')
        self.assertTrue(np.allclose(f.distance_change,.2))
    def odds(self):return pd.DataFrame({'馬番':[1,2],'status':['active']*2,'win_odds':[3,10],'odds_acquired_at':['2026-10-28T10:00:00Z']*2,'cutoff_at':['2026-10-28T10:05:00Z']*2})
    def test_valid_odds(self):self.assertEqual(len(validate_odds(self.odds(),[1,2],pd.Timestamp('2026-10-28T10:00:01Z'),pd.Timestamp('2026-10-28T10:05:00Z'))),2)
    def test_future_odds_rejected(self):
        with self.assertRaises(ValueError):validate_odds(self.odds(),[1,2],pd.Timestamp('2026-10-28T09:59:59Z'),pd.Timestamp('2026-10-28T10:05:00Z'))
    def test_missing_runner_odds_rejected(self):
        with self.assertRaises(ValueError):validate_odds(self.odds().iloc[:1],[1,2],pd.Timestamp('2026-10-28T10:00:01Z'),pd.Timestamp('2026-10-28T10:05:00Z'))
if __name__=='__main__':unittest.main()
