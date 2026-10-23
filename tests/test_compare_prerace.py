import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from nar_compare_prerace import compare, report
from nar_validation import REQUIRED, prepare


class CompareTests(unittest.TestCase):
    def fixture(self, root):
        root=Path(root); (root/'capture').mkdir()
        (root/'capture/manifest.json').write_text('{}')
        m=dict(capture_relative_path='capture',capture_manifest_sha256=hashlib.sha256(b'{}').hexdigest(),
            race_id='2026-10-23_18_01',venue='浦和',race=1,cutoff_at='2026-10-23T12:20:00+09:00',
            started_at='2026-10-23T12:15:00+09:00',score_generated_at='2026-10-23T12:15:30+09:00',files_written_at='2026-10-23T12:15:31+09:00')
        rows=[]
        for n,finish in [(1,4),(2,1),(3,2),(4,3)]:
            row={k:None for k in REQUIRED}
            row.update(race_date='2026-10-23',競馬場='浦和',レース番号=1,馬番=n,馬名=f'馬{n}',horse_key=f'key{n}',race_key='r',距離=1400,頭数=4,着順=finish)
            rows.append(row)
        h=prepare(pd.DataFrame(rows))
        entries=h[['馬番','馬名','horse_key']].copy();entries['status']='active'
        ratings=entries[['馬番','馬名']].copy();ratings['評価点']=[90,80,70,60];ratings['確かさ(%)']=50;ratings['identity_status']='matched'
        source=dict(race_id=m['race_id'],cutoff_at=m['cutoff_at'],snapshot_at='2026-10-23T12:15:15+09:00')
        return m,h,entries,ratings,source

    def call(self,root,parts):
        m,h,e,r,s=parts
        with patch('nar_compare_prerace.read_run',return_value=(m,{'ratings.csv':r})),patch('nar_compare_prerace.verify_capture',return_value=(e,1400,'良',s)):
            return compare(root,h)

    def test_saved_ranks_and_results(self):
        with tempfile.TemporaryDirectory() as t:
            frame,s=self.call(t,self.fixture(t))
            self.assertEqual(s['actual_top3_captured'],2)
            self.assertEqual(s['leader_finishes'],[4])
            self.assertEqual(frame.iloc[0]['着順差_実着順マイナス評価順位'],3)

    def test_ties_not_broken_by_horse_number(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);parts[3]['評価点']=[90,80,70,70]
            _,s=self.call(t,parts);self.assertEqual(s['top3_candidate_count'],4);self.assertTrue(s['score_ties'])

    def test_unmatched_missing_unranked(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);parts[3].loc[0,['評価点','identity_status']]=[float('nan'),'unmatched']
            frame,s=self.call(t,parts);self.assertEqual(s['scored_runners'],3);self.assertTrue(pd.isna(frame.iloc[-1]['事前評価順位']))

    def test_partial_results_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            parts=list(self.fixture(t));parts[1]=parts[1].iloc[:-1]
            with self.assertRaises(ValueError):self.call(t,parts)

    def test_wrong_identity_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);parts[1].loc[0,'horse_key']='other'
            with self.assertRaisesRegex(ValueError,'identity'):self.call(t,parts)

    def test_score_after_start_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);parts[0]['files_written_at']=parts[0]['cutoff_at']
            with self.assertRaisesRegex(ValueError,'pre-race'):self.call(t,parts)

    def test_capture_manifest_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);(Path(t)/'capture/manifest.json').write_text('changed')
            with self.assertRaisesRegex(ValueError,'hash'):self.call(t,parts)

    def test_dead_heat_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            parts=self.fixture(t);parts[1].loc[0,'着順_num']=3
            with self.assertRaises(ValueError):self.call(t,parts)

    def test_report_earliest_only_and_empty(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);parts=self.fixture(root)
            history=root/'results.csv';parts[1].to_csv(history,index=False)
            out=report(root/'none',history,root/'out')
            self.assertEqual(json.loads((out/'summary.json').read_text())['compared_races'],0)
            for name,time in [('a','12:15:31'),('b','12:16:31')]:
                p=root/'runs/2026-10-23/18-01'/name;p.mkdir(parents=True)
                (p/'run_manifest.json').write_text(json.dumps(dict(status='completed_prerace',race_id='r',files_written_at=f'2026-10-23T{time}+09:00')))
            with patch('nar_compare_prerace.compare',side_effect=ValueError('invalid earliest')) as comp:
                out=report(root/'runs',history,root/'out')
                self.assertEqual(comp.call_count,1)
                self.assertEqual(json.loads((out/'summary.json').read_text())['skipped_races'],1)
