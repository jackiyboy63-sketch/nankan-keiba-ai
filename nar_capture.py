"""Capture NAR public race pages; archive only, never purchases or fabricated scores."""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

JST=timezone(timedelta(hours=9))
VENUES={'浦和':18,'船橋':19,'大井':20,'川崎':21}
BASE='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/'

class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.text=[];self.rows=[];self.row=None;self.cell=None;self.target=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='table' and 'odd_popular_table_02' in attrs.get('class','').split():self.target=True
        if self.target and tag=='tr':self.row=[]
        if self.target and tag in ('td','th'):self.cell=[]
    def handle_data(self,data):
        self.text.append(data)
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if self.target and tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(''.join(self.cell).split()));self.cell=None
        if self.target and tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None
        if tag=='table':self.target=False

def metadata(html,day,venue,race):
    p=Page();p.feed(html);text=''.join(''.join(p.text).split())
    m=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日[（(][^）)]*[）)]'+re.escape(venue)+r'第(\d+)競走(\d{1,2}):(\d{2})発走',text)
    if not m:raise ValueError('race heading/time unavailable')
    y,mo,d,r,h,mi=map(int,m.groups())
    cutoff=datetime(y,mo,d,h,mi,tzinfo=JST)
    if cutoff.date().isoformat()!=day or r!=race:raise ValueError('race identity mismatch')
    return p,text,cutoff

def parse_odds(html,day,venue,race,received_at):
    p,text,cutoff=metadata(html,day,venue,race)
    if '最終' in text:raise ValueError('final odds rejected')
    if received_at.tzinfo is None or received_at>=cutoff:raise ValueError('not before scheduled start')
    rows=[];seen=set()
    for row in p.rows:
        if not row or row[0]=='枠':continue
        if len(row)!=13:raise ValueError('unexpected odds table layout')
        frame,horse,name,win,low,high,*rest=row
        if not horse.isdigit() or int(horse)<=0 or int(horse) in seen:raise ValueError('invalid/duplicate runner')
        seen.add(int(horse))
        status='excluded' if any(x in ''.join(row) for x in ('取消','除外','競走中止')) else 'active'
        if status=='active':
            if not re.fullmatch(r'\d+(?:\.\d+)?',win) or not re.fullmatch(r'\d+(?:\.\d+)?-',low) or not re.fullmatch(r'\d+(?:\.\d+)?',high):
                raise ValueError('missing or unrecognized odds')
            w,lo,hi=float(win),float(low[:-1]),float(high)
            if w<1 or lo<1 or hi<lo:raise ValueError('invalid odds range')
        else:w=lo=hi=None
        rows.append(dict(horse_no=int(horse),horse_name=name,status=status,win_odds=w,place_odds_low=lo,place_odds_high=hi))
    if not rows:raise ValueError('no odds runners')
    return rows,cutoff

def fetch(url):
    req=Request(url,headers={'User-Agent':'NankanKeibaAI/0.1 (research snapshot archive)','Cache-Control':'no-cache'})
    with urlopen(req,timeout=30) as response:
        if urlparse(response.geturl()).hostname not in ('www.keiba.go.jp','keiba.go.jp'):raise ValueError('unexpected redirect')
        raw=response.read(5_000_001)
        if len(raw)>5_000_000:raise ValueError('page too large')
        return raw,datetime.now(timezone.utc),dict(response.headers)

def capture(day,venue,race,output,fetcher=fetch):
    if venue not in VENUES or not 1<=race<=12:raise ValueError('unsupported venue/race')
    if datetime.fromisoformat(day).date()!=datetime.now(JST).date():raise ValueError('capture only today; past pages are not pre-race snapshots')
    folder=Path(output)/day/f'{VENUES[venue]}-{race:02d}'/(datetime.now(timezone.utc).strftime('%H%M%S%f')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    manifest={'schema_version':1,'race_id':f'{day}_{VENUES[venue]}_{race:02d}','venue':venue,'race':race,'status':'rejected','pages':[], 'limitations':['local receipt clock, not independent timestamp authentication','scheduled start only; no delayed-start inference','no score generation or v3 decision input export']}
    try:
        for endpoint in ('DebaTable','OddsTanFuku'):
            query=urlencode({'k_raceDate':day.replace('-','/'),'k_babaCode':VENUES[venue],'k_raceNo':race,'odds_flg':4})
            url=BASE+endpoint+'?'+query
            raw,received,headers=fetcher(url)
            (folder/(endpoint+'.html')).write_bytes(raw)
            manifest['pages'].append({'url':url,'received_at':received.isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'headers':{k:v for k,v in headers.items() if k.lower() in ('date','last-modified','content-type')}})
            html=raw.decode('utf-8-sig',errors='strict')
            if endpoint=='DebaTable':
                _,_,card_cutoff=metadata(html,day,venue,race)
                if received>=card_cutoff:raise ValueError('race card received after start')
            else:
                rows,cutoff=parse_odds(html,day,venue,race,received)
                if cutoff!=card_cutoff:raise ValueError('card/odds start-time mismatch')
        manifest.update(status='accepted_capture',cutoff_at=cutoff.isoformat(),snapshot_at=received.isoformat(),runners=len(rows))
        with (folder/'odds.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    except Exception as exc:
        manifest['reason']=f'{type(exc).__name__}: {exc}'
        raise
    finally:(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',default=datetime.now(JST).date().isoformat());p.add_argument('--venue',required=True,choices=VENUES);p.add_argument('--race',required=True,type=int);p.add_argument('--output',default='data/prerace')
    a=p.parse_args();print(capture(a.date,a.venue,a.race,a.output))
if __name__=='__main__':main()
