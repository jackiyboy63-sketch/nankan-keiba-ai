import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from nar_enriched_compare import enriched_features, FEATURES, COURSE, BLOOD, OPPONENT, predict
from nar_replay_enriched import make_frame, load_model_bundle, main

class EnrichedReplayTests(unittest.TestCase):
    def history(self):
        rows=[]
        for day in range(1,7):
            for i in range(1,5):
                rows.append(dict(race_date=f'2026-09-{day:02}',race_key=f'old{day}',horse_key=f'h{i}',馬番=i,着順=i,頭数=4,距離=1400,タイム=1300+i,競馬場='大井',父馬名='father',母父馬名='grandfather',**{'上がり3F':38+i}))
        return pd.DataFrame(rows)
    def entries(self):return pd.DataFrame({'馬番':[1,2,3,4],'horse_key':['h1','h2','h3','h4']})
    def frame(self,h=None,e=None):
        return make_frame(self.history() if h is None else h,self.entries() if e is None else e,'2026-10-28','大井',1400,'2026-10-28-20-01')
    def bundle(self):
        cols=FEATURES+COURSE+BLOOD+OPPONENT;n=len(cols)
        return {'selected_on_2025':{'features':cols},'models':{'selected':{'features':cols,'weights':[.1]*(2*n),'preprocessing':{'median':[0]*n,'mean':[0]*n,'scale':[1]*n},'temperature':1}}}
    def test_same_day_future_results_ignored(self):
        h=self.history();extra=h.copy();extra.race_date='2026-10-28';extra['父馬名']='poison'
        pd.testing.assert_frame_equal(self.frame(),self.frame(pd.concat([h,extra])))
        extra.race_date='2026-10-29'
        pd.testing.assert_frame_equal(self.frame(),self.frame(pd.concat([h,extra])))
    def test_card_results_and_pedigree_not_used(self):
        e=self.entries();e['着順']=1;e['タイム']=999;e['父馬名']='poison';e['母父馬名']='poison'
        pd.testing.assert_frame_equal(self.frame(),self.frame(e=e))
    def test_training_serving_feature_parity(self):
        target=self.history().tail(4).copy();target.race_date='2026-10-28';target.race_key='2026-10-28-20-01'
        full=enriched_features(pd.concat([self.history(),target],ignore_index=True))
        cols=FEATURES+COURSE+BLOOD+OPPONENT
        expected=full[full.race_key.eq('2026-10-28-20-01')].sort_values('馬番')[cols].reset_index(drop=True)
        actual=self.frame().sort_values('馬番')[cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected,actual)
        self.assertTrue(actual[BLOOD].notna().all().all())
    def test_string_distance(self):
        h=self.history();h['距離']=h['距離'].astype(str)
        pd.testing.assert_frame_equal(self.frame(),self.frame(h))
    def test_new_runner_rejects_race(self):
        e=self.entries();e.loc[0,'horse_key']='unknown'
        with self.assertRaisesRegex(ValueError,'全馬'):self.frame(e=e)
    def test_model_validation(self):
        b=self.bundle();m=load_model_bundle(b)
        p=predict(self.frame(),m,m['temperature']);self.assertAlmostEqual(p.sum(),1);self.assertTrue(np.isfinite(p).all())
        for field in ['weights','temperature','preprocessing']:
            bad=copy.deepcopy(b)
            if field=='weights':bad['models']['selected'][field]=[0]
            elif field=='temperature':bad['models']['selected'][field]=float('nan')
            else:bad['models']['selected'][field]['scale'][0]=0
            with self.assertRaises(ValueError):load_model_bundle(bad)
    def test_cli_outputs_and_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.history().to_csv(root/'history.csv',index=False)
            (root/'models.json').write_text(json.dumps(self.bundle()))
            folder=root/'runs'/'one';folder.mkdir(parents=True)
            m={'status':'completed_prerace','files_written_at':'2026-10-28T01:00:00Z','race_id':'2026-10-28-20-01','cutoff_at':'2026-10-28T01:05:00Z','venue':'大井'}
            (folder/'run_manifest.json').write_text(json.dumps(m))
            odds=pd.DataFrame({'馬番':[1,2,3,4],'win_odds':[10]*4,'odds_acquired_at':['2026-10-28T00:59:59Z']*4})
            args=['run','--model',str(root/'models.json'),'--history',str(root/'history.csv'),'--runs',str(root/'runs'),'--output',str(root/'out')]
            with patch('sys.argv',args),patch('nar_replay_enriched.load_verified',return_value=(m,self.entries(),1400,odds)):
                main()
            info=json.loads((root/'out/manifest.json').read_text());self.assertEqual(info['probability_races'],1);self.assertEqual(info['candidate_races'],1)
            self.assertEqual(info['mode'],'retrospective_replay_not_live')
            m['race_id']='2026-09-30-20-01';(folder/'run_manifest.json').write_text(json.dumps(m));args[-1]=str(root/'out2')
            with patch('sys.argv',args),patch('nar_replay_enriched.load_verified',return_value=(m,self.entries(),1400,odds)):
                main()
            info=json.loads((root/'out2/manifest.json').read_text());self.assertEqual(info['probability_races'],0);self.assertEqual(info['unavailable_records'],1)

if __name__=='__main__':unittest.main()
