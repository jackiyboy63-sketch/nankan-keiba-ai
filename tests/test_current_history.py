import unittest
import pandas as pd
from nar_current_history import result_rows, merge_history
import test_prerace_rating as fixtures
CARD = fixtures.CARD
from nar_prerace_rating import parse_card, rate_entries

class CurrentHistoryTests(unittest.TestCase):
    def card(self): return parse_card(CARD,'2026-10-23','大井',1)[0]
    def result(self, rank='1', clock='1:40.0'):
        return f'''2026年10月23日（金）大井第1競走競走成績 ダート1600ｍ 馬場：良
<section class="gradeTable"><table><tr class="tBorder"><td class="a">{rank}</td><td class="c">1</td><td class="d"><a href="?k_lineageLoginCode=123">テスト</a></td><td class="k">{clock}</td><td class="m">40.0</td></tr></table></section>'''
    def test_result_time_and_identity(self):
        r=result_rows(self.result(),'2026-10-23','大井',1,self.card())
        self.assertEqual(r.iloc[0]['タイム'],1400)
    def test_result_wrong_date(self):
        with self.assertRaisesRegex(ValueError,'identity'):result_rows(self.result(),'2026-10-22','大井',1,self.card())
    def test_special_results_quarantined(self):
        for rank,clock in [('取消',''),('中止',''),('2','1:40.0')]:
            with self.assertRaises(ValueError):result_rows(self.result(rank,clock),'2026-10-23','大井',1,self.card())
    def test_result_wrong_identity(self):
        with self.assertRaisesRegex(ValueError,'identity'):result_rows(self.result().replace('Code=123','Code=999'),'2026-10-23','大井',1,self.card())
    def test_merge_no_duplicate_baselines(self):
        h=fixtures.PreraceRatingTests().history();r=merge_history(h,h.copy(),'2026-10-23');self.assertEqual(len(r),1)
    def test_merge_conflict_is_error(self):
        h=fixtures.PreraceRatingTests().history();s=h.copy();s['タイム']=1450
        with self.assertRaisesRegex(ValueError,'conflicting'):merge_history(h,s,'2026-10-23')
    def test_merge_future_same_day_rejected(self):
        h=fixtures.PreraceRatingTests().history()
        for day in ['2026-10-23','2026-10-24']:
            s=h.copy();s['race_date']=day
            with self.assertRaisesRegex(ValueError,'future'):merge_history(h,s,'2026-10-23')
    def test_unraced_diagnostic_and_empty_score(self):
        helper=fixtures.PreraceRatingTests();h=helper.history();h['horse_key']='different';h['馬名']='別馬'
        e=helper.entries();e['official_declared_starts']=0
        r=helper.rate(h,e);self.assertTrue(r.iloc[0]['評価状態'].startswith('未出走'));self.assertTrue(pd.isna(r.iloc[0]['評価点']))
    def test_identity_conflict_diagnostic(self):
        helper=fixtures.PreraceRatingTests();h=helper.history();h['horse_key']='different';r=helper.rate(h)
        self.assertTrue(r.iloc[0]['評価状態'].startswith('照合不一致'))
    def test_old_history_diagnostic(self):
        helper=fixtures.PreraceRatingTests();h=helper.history();h['race_date']='2023-01-01';r=helper.rate(h)
        self.assertTrue(r.iloc[0]['評価状態'].startswith('履歴不足'));self.assertTrue(pd.isna(r.iloc[0]['評価点']))

    def test_collector_cache_and_manifest(self):
        import tempfile, json
        from pathlib import Path
        from datetime import datetime, timezone
        from nar_current_history import collect
        listing='<a href="RaceMarkTable?k_raceDate=2026%2F10%2F23&amp;k_babaCode=20&amp;k_raceNo=1">1R</a>'
        calls=[]
        def fetch(url):
            calls.append(url)
            raw=listing if '/RaceList?' in url else CARD if '/DebaTable?' in url else self.result()
            return raw.encode(),datetime(2026,10,26,tzinfo=timezone.utc),{}
        with tempfile.TemporaryDirectory() as tmp:
            data,m=collect('2026-10-23','2026-10-24',['大井'],tmp,fetcher=fetch,pause=lambda _:None)
            self.assertEqual(len(data),1);self.assertEqual(m['coverage'],'verified_requested_links');self.assertEqual(len(calls),3)
            collect('2026-10-23','2026-10-24',['大井'],tmp,fetcher=fetch,pause=lambda _:None)
            self.assertEqual(len(calls),3)
            next(Path(tmp).rglob('DebaTable-1.html')).write_text('tampered')
            data,m=collect('2026-10-23','2026-10-24',['大井'],tmp,fetcher=fetch,pause=lambda _:None)
            self.assertEqual(len(data),0);self.assertEqual(len(m['rejected']),1)
    def test_supplement_partial_race_rejected(self):
        h=fixtures.PreraceRatingTests().history();s=h.copy();s['頭数']=2
        with self.assertRaisesRegex(ValueError,'頭数'):merge_history(h,s,'2026-10-23')
