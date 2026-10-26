"""Rate verified archived pre-race entries using strictly earlier historical starts."""
import argparse
import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import pandas as pd
from nar_capture import metadata,parse_odds,VENUES
from nar_validation import REQUIRED
from nar_rating_v2 import rating

def plain(value):return ''.join(unescape(re.sub('<[^>]+>','',value)).split())

def parse_card(html,day,venue,race):
    _,text,cutoff=metadata(html,day,venue,race)
    distance=re.search(r'ダート(\d+)[ｍm]',text)
    going=re.search(r'馬場[：:](良|稍重|重|不良)',text)
    if not distance or not going:raise ValueError('distance/going unavailable')
    entries=[]
    for block in re.split(r'<tr\s+class=["\']tBorder["\']\s*>',html)[1:]:
        no=re.search(r'<td[^>]*class=["\']horseNum["\'][^>]*>(.*?)</td>',block,re.S)
        horse=re.search(r'<a[^>]*class=["\']horseName["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',block,re.S)
        if not no or not horse:raise ValueError('unrecognized runner block')
        ident=re.search(r'k_lineageLoginCode=(\d+)',unescape(horse[1]))
        ancestry=re.findall(r'<td\s+colspan=["\']3["\']\s*>(.*?)</td>',block,re.S)
        age=re.search(r'>\s*(?:牡|牝|セン|セ)(\d+)\s*<',block)
        birth=re.search(r'(\d{2})\.(\d{2})生',plain(block))
        if not ident or len(ancestry)<5 or not age or not birth:raise ValueError('runner identity fields unavailable')
        stats=re.search(r'<td[^>]*>\s*全(?:&nbsp;|\s)*</td>(.*?)</tr>',block,re.S)
        counts=re.findall(r'<td[^>]*>(.*?)</td>',stats[1],re.S) if stats else []
        values=[plain(x).strip('-') for x in counts[:4]]
        starts=sum(map(int,values)) if len(values)==4 and all(x.isdigit() for x in values) else None
        name=plain(horse[2]);sire,dam,bms=map(plain,ancestry[2:5]);bms=bms.strip('（）()')
        birthday=pd.Timestamp(year=int(day[:4])-int(age[1]),month=int(birth[1]),day=int(birth[2])).strftime('%Y%m%d')
        entries.append({'馬番':int(plain(no[1])),'馬名':name,'生年月日':birthday,'父馬名':sire,'母馬名':dam,'母父馬名':bms,'official_declared_starts':starts,'official_horse_id':ident[1],'horse_key':'|'.join([name,birthday,sire,dam])})
    frame=pd.DataFrame(entries)
    if frame.empty or frame['馬番'].duplicated().any() or frame.official_horse_id.duplicated().any():raise ValueError('missing/duplicate card runners')
    return frame,int(distance[1]),going[1],cutoff

def verify_capture(folder):
    folder=Path(folder);m=json.loads((folder/'manifest.json').read_text())
    if m.get('status')!='accepted_capture':raise ValueError('capture not accepted')
    race_id=m['race_id'];day=race_id[:10];venue=m['venue'];race=int(m['race'])
    if race_id!=f'{day}_{VENUES[venue]}_{race:02d}':raise ValueError('manifest race identity mismatch')
    records={}
    for endpoint in ['DebaTable','OddsTanFuku']:
        matches=[x for x in m['pages'] if '/'+endpoint+'?' in x['url']]
        if len(matches)!=1:raise ValueError('missing/duplicate source page')
        record=matches[0];raw=(folder/(endpoint+'.html')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('source hash mismatch')
        received=pd.Timestamp(record['received_at'])
        if received.tzinfo is None:raise ValueError('missing acquisition timezone')
        records[endpoint]=(raw.decode('utf-8-sig'),received)
    card,distance,going,cutoff=parse_card(records['DebaTable'][0],day,venue,race)
    if records['DebaTable'][1]>=cutoff:raise ValueError('card acquired after start')
    odds,odds_cutoff=parse_odds(records['OddsTanFuku'][0],day,venue,race,records['OddsTanFuku'][1])
    o=pd.DataFrame(odds)
    if cutoff!=odds_cutoff or pd.Timestamp(m['cutoff_at'])!=cutoff:raise ValueError('start mismatch')
    if set(card['馬番'])!=set(o.horse_no):raise ValueError('card/odds runner set differs')
    joined=card.merge(o,left_on='馬番',right_on='horse_no',validate='one_to_one')
    if joined['馬名'].ne(joined.horse_name).any():raise ValueError('card/odds name mismatch')
    return joined,distance,going,m

def rate_entries(history,entries,day,venue,race,distance,going):
    h=history.copy();h['race_date']=pd.to_datetime(h.race_date,errors='raise')
    h=h[h.race_date<pd.Timestamp(day)].copy()
    active=entries[entries.status.eq('active')].copy()
    if active.empty:raise ValueError('no active runners')
    known=set(h.horse_key)
    # Exact identity only; never fall back to names or future rows.
    active['identity_status']=active.horse_key.map(lambda x:'matched' if x in known else 'unmatched')
    targets=[]
    for _,e in active.iterrows():
        row={k:None for k in REQUIRED}
        row.update({k:e[k] for k in ['馬番','馬名','horse_key','父馬名','母父馬名']})
        row.update(race_date=day,競馬場=venue,レース番号=race,距離=distance,頭数=len(active),馬場=going,race_key=f'prerace|{day}|{venue}|{race}')
        targets.append(row)
    result=rating(pd.concat([h,pd.DataFrame(targets)],ignore_index=True),day,venue,race)
    result=result.drop(columns=['実際の着順(検証用)'])
    diagnostics=[]
    for _,e in active.iterrows():
        prior=h[h.horse_key.eq(e.horse_key)]
        recent=prior[prior.race_date>=pd.Timestamp(day)-pd.Timedelta(days=730)]
        if not recent.empty: reason='評価可能'
        elif not prior.empty: reason='履歴不足：評価期間内の出走なし'
        elif pd.notna(e.get('official_declared_starts')) and e.get('official_declared_starts')==0: reason='未出走：公式出走表の全成績0走'
        elif h['馬名'].eq(e['馬名']).any(): reason='照合不一致：同名馬の識別情報が一致しない'
        else: reason='履歴不足：収録範囲に一致する過去走なし'
        diagnostics.append({'馬番':e['馬番'],'評価状態':reason})
    result=result.merge(active[['馬番','official_horse_id','identity_status']],on='馬番',validate='one_to_one')
    result=result.merge(pd.DataFrame(diagnostics),on='馬番',validate='one_to_one')
    missing=result['評価状態'].ne('評価可能')
    result.loc[missing,['評価点','確かさ(%)']]=float('nan')
    return result.sort_values(['評価点','馬番'],ascending=[False,True],na_position='last')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',required=True);p.add_argument('--history',default='data/processed/horse_history.csv');p.add_argument('--output',required=True)
    a=p.parse_args();entries,distance,going,m=verify_capture(a.capture)
    h=pd.read_csv(a.history,encoding='utf-8-sig',dtype={'生年月日':str},low_memory=False)
    result=rate_entries(h,entries,m['race_id'][:10],m['venue'],int(m['race']),distance,going)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    result.to_csv(out/'ratings.csv',index=False,encoding='utf-8-sig')
    entries.to_csv(out/'verified_entries.csv',index=False,encoding='utf-8-sig')
    (out/'manifest.json').write_text(json.dumps({'model':'existing_v2','score_generated_at':pd.Timestamp.now(tz='UTC').isoformat(),'capture_manifest_sha256':hashlib.sha256((Path(a.capture)/'manifest.json').read_bytes()).hexdigest(),'history_sha256':hashlib.sha256(Path(a.history).read_bytes()).hexdigest(),'limitations':['experimental v2, not calibrated probability','offline regeneration is not a historical pre-race score snapshot','no v3 decision export; no purchase']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(result[['馬番','馬名','評価点','確かさ(%)','identity_status']].to_string(index=False))
if __name__=='__main__':main()
