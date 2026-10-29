import unittest
import numpy as np
import pandas as pd
from nar_decision_v3 import fit_calibration, calibrated_probability, decide

class Guardrails(unittest.TestCase):
    def training(self):
        return pd.DataFrame({'race_id':['a','a','b','b'], 'score':[10,20,30,40],
                             'won':[0,1,0,1], 'race_date':['2026-10-27']*4})

    def snapshot(self):
        return pd.DataFrame({'race_id':['r'], 'horse_no':[1], 'score':[30],
            'snapshot_at':['2026-10-29T18:00:00+09:00'],
            'cutoff_at':['2026-10-29T18:05:00+09:00'],
            'win_odds':[10], 'place_odds':[2], 'source':['fixture']})

    def model(self):
        return {'edges':[0,100], 'rates':[0.2], 'training_end':'2026-10-28'}

    def test_nonfinite_training_rejected(self):
        d=self.training(); d.loc[0,'score']=np.inf
        with self.assertRaises(ValueError): fit_calibration(d,min_races=2)

    def test_invalid_training_dates_rejected(self):
        for bad in ['bad','2026-10-28']:
            d=self.training(); d.loc[0,'race_date']=bad
            with self.assertRaises(ValueError): fit_calibration(d,min_races=2)

    def test_invalid_models_rejected(self):
        for model in [{'edges':[0,0], 'rates':[.5]}, {'edges':[0,1], 'rates':[1.1]},
                      {'edges':[0,1], 'rates':[]}, {'edges':[0,np.inf], 'rates':[.5]}]:
            with self.assertRaises(ValueError): calibrated_probability(pd.Series([.5]),model)

    def test_same_japan_day_training_rejected(self):
        m=self.model(); m['training_end']='2026-10-29'
        with self.assertRaises(ValueError): decide(self.snapshot(),{'win':m},as_of='2026-10-29T18:00:00+09:00')

    def test_budget_checked_without_model(self):
        with self.assertRaises(ValueError): decide(self.snapshot(),None,as_of='2026-10-29T18:00:00+09:00',already_spent=5100)

    def test_positive_ev_and_budget(self):
        s=self.snapshot(); m={'win':self.model()}
        b=decide(s,m,as_of='2026-10-29T18:00:00+09:00',already_spent=4900)
        self.assertEqual(len(b),1); self.assertEqual(b.iloc[0].stake_yen,100)
        self.assertEqual(b.iloc[0].edge,1)
        self.assertTrue(decide(s,m,as_of='2026-10-29T18:00:00+09:00',already_spent=5000).empty)

    def test_negative_ev_skipped(self):
        s=self.snapshot(); s['win_odds']=2
        self.assertTrue(decide(s,{'win':self.model()},as_of='2026-10-29T18:00:00+09:00').empty)

if __name__=='__main__': unittest.main()
