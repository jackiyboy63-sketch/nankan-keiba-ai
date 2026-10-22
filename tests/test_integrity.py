import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
import subprocess
import tempfile
import zipfile
import pandas as pd
from pandas.testing import assert_frame_equal
from nar_validation import parse_seconds, prepare
from nar_rating import rating as v1
from nar_rating_v2 import rating as v2
from nar_walkforward import payout, summarize


def history():
    rows=[]
    for day in ['2026-01-01','2026-01-02','2026-02-01','2026-03-01']:
        for h in range(1,4):
            rows.append(dict(race_date=day,競馬場='浦和',レース番号=1,horse_key=str(h),
                             race_key=day+'|浦和|1',父馬名='父',母父馬名='母父',馬番=h,馬名='馬'+str(h),
                             着順=h,距離=1400,頭数=3,上がり3F=38+h,タイム=1300+h*10,馬場='良'))
    return pd.DataFrame(rows)


class Integrity(unittest.TestCase):
    def test_packed_times(self):
        self.assertEqual(parse_seconds(1314),91.4)
        self.assertEqual(parse_seconds(598),59.8)
        for x in [0,1600,-1,'abc',float('nan')]:
            self.assertTrue(pd.isna(parse_seconds(x)))

    def test_target_results_and_future_do_not_change_features(self):
        d=history()
        changed=d.copy()
        mask=changed.race_date.ge('2026-02-01')
        for col in ['着順','タイム','上がり3F']:
            changed.loc[mask,col]=999
        for fn in [v1,v2]:
            expected=fn(d,'2026-02-01','浦和',1).drop(columns='実際の着順(検証用)')
            actual=fn(changed,'2026-02-01','浦和',1).drop(columns='実際の着順(検証用)')
            assert_frame_equal(expected,actual)

    def test_shuffle_does_not_break_ties(self):
        # Make each past race retain distinct horse keys, but target horses have no past.
        d=history(); d.loc[d.race_date.lt('2026-02-01'),'horse_key']+='past'
        for fn in [v1,v2]:
            a=fn(d,'2026-02-01','浦和',1).reset_index(drop=True)
            b=fn(d.sample(frac=1,random_state=42),'2026-02-01','浦和',1).reset_index(drop=True)
            assert_frame_equal(a,b)
            self.assertEqual(a['馬番'].tolist(),[1,2,3])

    def test_missing_runner_rejected(self):
        d=history();d=d[~(d.race_date.eq('2026-02-01') & d['馬番'].eq(3))]
        for fn in [v1,v2]:
            with self.assertRaisesRegex(ValueError,'頭数'):
                fn(d,'2026-02-01','浦和',1)

    def test_duplicate_runner_rejected(self):
        d=history()
        with self.assertRaisesRegex(ValueError,'重複'):
            prepare(pd.concat([d,d.iloc[:1]]))

    def test_winner_clock_missing_not_replaced_by_runner_up(self):
        d=history();d.loc[d['着順'].eq(1),'タイム']=None
        for fn in [v1,v2]:
            result=fn(d,'2026-02-01','浦和',1)
            self.assertTrue(result['時計'].isna().all())

    def test_payouts_missing_conflict_and_zero(self):
        d=pd.DataFrame({'単勝組番':[2],'単勝払戻金（円）':[800]})
        self.assertEqual(payout(d,'top1_win',[2]),800)
        self.assertEqual(payout(d,'top1_win',[1]),0)
        with self.assertRaises(ValueError):
            payout(d.assign(**{'単勝払戻金（円）':None}),'top1_win',[1])
        with self.assertRaises(ValueError):
            payout(pd.concat([d,d.assign(**{'単勝払戻金（円）':900})]),'top1_win',[2])

    def test_drawdown_includes_initial_loss(self):
        d=pd.DataFrame([dict(model='v1',policy='top1_win',date='2026-01-01',track='浦和',race=i,
                             stake_yen=100,return_yen=ret) for i,ret in enumerate([0,0,500,0],1)])
        s=summarize(d).iloc[0]
        self.assertEqual(s.roi_pct,125)
        self.assertEqual(s.max_drawdown_yen,200)
        self.assertEqual(s.roi_without_largest_return_pct,0)

    def test_identity_conflict_quarantines_whole_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=history().iloc[:3].copy()
            d['競走年月日']='20260101';d['生年月日']='20200101';d['母馬名']='母'
            conflict=d.iloc[:1].copy();conflict['着順']=2
            with zipfile.ZipFile(Path(tmp)/'data.zip','w') as z:
                z.writestr('horselist.csv',pd.concat([d,conflict]).to_csv(index=False))
                z.writestr('racelist.csv',d[['競馬場','競走年月日','レース番号','距離','馬場','頭数']].iloc[:1].to_csv(index=False))
            out=Path(tmp)/'out'
            subprocess.run([sys.executable,'nar_history.py','--input',tmp,'--output',str(out)],check=True,capture_output=True)
            result=pd.read_csv(out/'horse_history.csv')
            self.assertTrue(result.empty)
            self.assertEqual(len(pd.read_csv(out/'quarantined_races.csv')),1)

if __name__=='__main__':
    unittest.main()
