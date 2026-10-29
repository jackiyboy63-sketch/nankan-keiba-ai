import unittest
import numpy as np
import pandas as pd
from nar_learn_history import features, complete_races, fit, predict, probabilities

class LearningTests(unittest.TestCase):
    def raw(self):
        rows=[]
        for day in range(1,6):
            for horse in range(1,5):
                rows.append(dict(race_date=f'2025-01-{day:02d}',race_key=f'r{day}',horse_key=f'h{horse}',
                    馬番=horse,着順=horse,頭数=4,距離=1400,タイム=1300+horse,競馬場='大井',**{'上がり3F':38+horse}))
        return pd.DataFrame(rows)
    def test_target_and_future_results_do_not_change_prior_features(self):
        a=self.raw();b=a.copy();b.loc[b.race_date.ge('2025-01-04'),'着順']=[4,3,2,1]*2
        b.loc[b.race_date.ge('2025-01-04'),'タイム']=1500
        f=features(a);g=features(b)
        cols=['form5','win5','clock5','closing5','log_starts','rest_days','distance_change','same_track']
        pd.testing.assert_frame_equal(f.loc[f.race_date.eq('2025-01-04'),cols],g.loc[g.race_date.eq('2025-01-04'),cols])
    def test_race_probabilities_sum_to_one(self):
        d,_=complete_races(features(self.raw()));m=fit(d,steps=30);p=predict(d,m)
        self.assertTrue(np.allclose(pd.Series(p,index=d.index).groupby(d.race_key).sum(),1))
        self.assertTrue(((p>0)&(p<1)).all())
    def test_no_prior_history_excludes_whole_race(self):
        d,_=complete_races(features(self.raw()))
        self.assertNotIn('r1',set(d.race_key))
    def test_duplicate_same_day_horse_rejected(self):
        raw=self.raw();raw=pd.concat([raw,raw.iloc[[0]]],ignore_index=True)
        with self.assertRaises(ValueError):features(raw)
    def test_training_learns_from_prior_signal(self):
        d,_=complete_races(features(self.raw()))
        m=fit(d,steps=100)
        p=predict(d,m)
        selected=p[d.won.to_numpy()==1]
        self.assertGreater(float(selected.mean()),.25)

    def test_stable_softmax(self):
        p=probabilities(np.array([10000.,10001.]),['a','a'])
        self.assertTrue(np.isfinite(p).all());self.assertAlmostEqual(p.sum(),1)
if __name__=='__main__':unittest.main()
