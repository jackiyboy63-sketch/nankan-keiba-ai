import unittest
import tempfile
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from nar_capture import parse_odds,capture,JST

class CaptureTests(unittest.TestCase):
    def page(self,win='5.0',low='1.2-',high='2.3',status=''):
        cells=['1','1','テスト馬',win,low,high,'牡3','','56','騎手','大井','調教師',status]
        return '2026年10月23日（金） 大 井 第1競走 18:00発走<table class="odd_popular_table_02"><tr>'+''.join('<td>'+x+'</td>' for x in cells)+'</tr></table>'
    def parse(self,page):return parse_odds(page,'2026-10-23','大井',1,datetime(2026,10,23,17,tzinfo=JST))
    def test_range_preserved(self):
        rows,_=self.parse(self.page());self.assertEqual((rows[0]['place_odds_low'],rows[0]['place_odds_high']),(1.2,2.3))
    def test_final_rejected(self):
        with self.assertRaisesRegex(ValueError,'final'):self.parse(self.page()+'（最終）')
    def test_after_start_rejected(self):
        with self.assertRaisesRegex(ValueError,'before'):parse_odds(self.page(),'2026-10-23','大井',1,datetime(2026,10,23,18,tzinfo=JST))
    def test_identity_mismatch(self):
        with self.assertRaisesRegex(ValueError,'identity'):parse_odds(self.page(),'2026-10-23','大井',2,datetime(2026,10,23,17,tzinfo=JST))
    def test_missing_odds_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.page(win='---'))
    def test_inverted_range_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.page(low='3.0-'))
    def test_scratch_not_imputed(self):
        rows,_=self.parse(self.page(win='',low='',high='',status='取消'));self.assertIsNone(rows[0]['win_odds']);self.assertEqual(rows[0]['status'],'excluded')
    def test_past_capture_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError,'today'):capture('2000-01-01','大井',1,'unused',fetcher=lambda u:self.fail('network called'))
    def test_archive_and_failure_manifest(self):
        today=datetime.now(JST).date().isoformat()
        y,m,d=map(int,today.split('-'))
        page=self.page().replace('2026年10月23日',f'{y}年{m}月{d}日')
        received=datetime(y,m,d,17,tzinfo=JST)
        def fetcher(url):return page.encode(),received,{'Date':'test'}
        with tempfile.TemporaryDirectory() as tmp:
            folder=capture(today,'大井',1,tmp,fetcher=fetcher)
            manifest=json.loads((folder/'manifest.json').read_text())
            self.assertEqual(manifest['status'],'accepted_capture')
            self.assertTrue((folder/'DebaTable.html').exists());self.assertTrue((folder/'odds.csv').exists())
        def final(url):return (page+'最終').encode(),received,{}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'final'):capture(today,'大井',1,tmp,fetcher=final)
            manifest=json.loads(next(Path(tmp).rglob('manifest.json')).read_text())
            self.assertEqual(manifest['status'],'rejected');self.assertFalse(list(Path(tmp).rglob('odds.csv')))
