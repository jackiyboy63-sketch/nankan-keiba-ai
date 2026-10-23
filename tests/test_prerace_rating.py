import unittest
import tempfile,json,hashlib
from pathlib import Path
import pandas as pd
from nar_prerace_rating import parse_card,rate_entries,verify_capture
from nar_validation import REQUIRED

CARD='''2026年10月23日（金）大井第1競走18:00発走 ダート1600ｍ 馬場：良
<tr class="tBorder"><td class="horseNum">1</td><td colspan="3"><a class="horseName" href="HorseMarkInfo?k_lineageLoginCode=123">テスト</a></td><td colspan="3">良1:40.0</td><td>牡3</td><td>03.25生</td><td colspan="3">父</td><td colspan="3">母</td><td colspan="3">（母父）</td></tr>'''
class PreraceRatingTests(unittest.TestCase):
    def entries(self):
        c,_,_,_=parse_card(CARD,'2026-10-23','大井',1);c['status']='active';return c
    def history(self):
        r={k:None for k in REQUIRED}
        r.update(race_date='2026-09-01',競馬場='大井',レース番号=1,距離=1600,頭数=1,馬場='良',馬番=1,馬名='テスト',horse_key='テスト|20230325|父|母',race_key='past',父馬名='父',母父馬名='母父',着順=1,タイム=1400,上がり3F=40)
        return pd.DataFrame([r])
    def rate(self,h,e=None):return rate_entries(h,self.entries() if e is None else e,'2026-10-23','大井',1,1600,'良')
    def test_full_identity(self):
        c=self.entries();self.assertEqual(c.iloc[0].horse_key,'テスト|20230325|父|母');self.assertEqual(c.iloc[0].official_horse_id,'123')
    def test_missing_identity_rejected(self):
        with self.assertRaises(ValueError):parse_card(CARD.replace('03.25生',''),'2026-10-23','大井',1)
    def test_duplicate_runner_rejected(self):
        with self.assertRaises(ValueError):parse_card(CARD+CARD,'2026-10-23','大井',1)
    def test_exact_history_match(self):
        r=self.rate(self.history());self.assertEqual(r.iloc[0].identity_status,'matched');self.assertNotIn('実際の着順(検証用)',r.columns)
    def test_name_only_not_matched(self):
        h=self.history();h['horse_key']='テスト|20220325|別の父|母';r=self.rate(h);self.assertTrue(pd.isna(r.iloc[0]['評価点']))
    def test_future_history_not_used_even_for_identity(self):
        h=self.history();h['race_date']='2026-10-24';r=self.rate(h);self.assertEqual(r.iloc[0].identity_status,'unmatched')
    def test_odds_do_not_change_score(self):
        e=self.entries();e['win_odds']=1.1;a=self.rate(self.history(),e);e['win_odds']=500;b=self.rate(self.history(),e)
        pd.testing.assert_frame_equal(a,b)

    def archive(self,folder,name='テスト',horse='1'):
        card=CARD
        cells=['1',horse,name,'5.0','1.2-','2.3','牡3','','56','騎手','大井','調教師','']
        odds='2026年10月23日（金）大井第1競走18:00発走<table class="odd_popular_table_02"><tr>'+''.join('<td>'+x+'</td>' for x in cells)+'</tr></table>'
        pages=[]
        for endpoint,html in [('DebaTable',card),('OddsTanFuku',odds)]:
            raw=html.encode();(folder/(endpoint+'.html')).write_bytes(raw)
            pages.append(dict(url='https://www.keiba.go.jp/'+endpoint+'?x=1',received_at='2026-10-23T17:00:00+09:00',sha256=hashlib.sha256(raw).hexdigest()))
        (folder/'manifest.json').write_text(json.dumps(dict(status='accepted_capture',race_id='2026-10-23_20_01',venue='大井',race=1,cutoff_at='2026-10-23T18:00:00+09:00',pages=pages)))
    def test_verified_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.archive(p);e,_,_,_=verify_capture(p);self.assertEqual(len(e),1)
    def test_tampered_capture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.archive(p);(p/'DebaTable.html').write_text(CARD+'changed')
            with self.assertRaisesRegex(ValueError,'hash'):verify_capture(p)
    def test_card_odds_name_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.archive(p,name='別馬')
            with self.assertRaisesRegex(ValueError,'name'):verify_capture(p)
    def test_card_odds_runner_set_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.archive(p,horse='2')
            with self.assertRaisesRegex(ValueError,'runner set'):verify_capture(p)
