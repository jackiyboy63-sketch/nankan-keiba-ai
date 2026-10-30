import unittest
import numpy as np,pandas as pd
from nar_enriched_compare import enriched_features,COURSE,BLOOD,OPPONENT,fit,predict
from nar_learn_history import FEATURES,complete_races
class EnrichedTests(unittest.TestCase):
    def raw(self):
        rows=[]
        for day in range(1,7):
            for h in range(1,5):
                rows.append(dict(race_date=f'2025-01-{day:02d}',race_key=f'r{day}',horse_key=f'h{h}',馬番=h,着順=h,頭数=4,距離=1400,タイム=1300+h,競馬場='大井',父馬名='父',母父馬名='母父',**{'上がり3F':38+h}))
        return pd.DataFrame(rows)
    def test_target_future_results_do_not_change_enriched_features(self):
        a=self.raw();b=a.copy();mask=b.race_date.ge('2025-01-05');b.loc[mask,'着順']=[4,3,2,1]*2;b.loc[mask,'タイム']=1400
        f=enriched_features(a);g=enriched_features(b);cols=FEATURES+COURSE+BLOOD+OPPONENT
        pd.testing.assert_frame_equal(f.loc[f.race_date.eq('2025-01-05'),cols],g.loc[g.race_date.eq('2025-01-05'),cols])
    def test_bloodline_minimum_prior_starts(self):
        d=enriched_features(self.raw())
        self.assertTrue(d.loc[d.race_date.eq('2025-01-03'),'sire_course_form'].isna().all())
        self.assertTrue(d.loc[d.race_date.eq('2025-01-04'),'sire_course_form'].notna().all())
    def test_course_does_not_use_other_track(self):
        r=self.raw();r.loc[r.race_date.eq('2025-01-06'),'競馬場']='浦和'
        d=enriched_features(r);g=d[d.race_date.eq('2025-01-06')]
        self.assertTrue(g.course_form.isna().all());self.assertTrue(g.distance_form.notna().all())
    def test_missing_parent_stays_missing(self):
        r=self.raw();r['父馬名']=None;d=enriched_features(r)
        self.assertTrue(d.sire_course_form.isna().all())
    def test_enriched_predictions_sum_to_one(self):
        d,_=complete_races(enriched_features(self.raw()));m=fit(d,FEATURES+COURSE+BLOOD+OPPONENT,.02);p=predict(d,m)
        self.assertTrue(np.allclose(pd.Series(p,index=d.index).groupby(d.race_key).sum(),1))
if __name__=='__main__':unittest.main()
