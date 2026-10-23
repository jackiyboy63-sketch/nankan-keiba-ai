"""One-shot capture, verify and rate. No purchase or calibrated betting decision."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import pandas as pd
from nar_capture import capture,VENUES,JST
from nar_prerace_rating import verify_capture,rate_entries

def now_utc():return datetime.now(timezone.utc)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(venue,race,history='data/processed/horse_history.csv',output='data/prerace_runs',max_age_seconds=180,clock=now_utc):
    if venue not in VENUES or not 1<=race<=12:raise ValueError('unsupported venue/race')
    if not 0<max_age_seconds<=600:raise ValueError('freshness limit must be 1..600 seconds')
    history=Path(history)
    if not history.is_file():raise ValueError('history missing; run nar_history.py first')
    # Load once, hash the exact bytes used, before collecting time-sensitive pages.
    raw=history.read_bytes()
    import io
    h=pd.read_csv(io.BytesIO(raw),encoding='utf-8-sig',dtype={'生年月日':str},low_memory=False)
    start=pd.Timestamp(clock())
    if start.tzinfo is None:raise ValueError('clock timezone missing')
    day=start.tz_convert(JST).date().isoformat()
    folder=Path(output)/day/f'{VENUES[venue]}-{race:02d}'/(start.strftime('%H%M%S%f')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    m={'schema_version':1,'status':'failed','venue':venue,'race':race,'started_at':start.isoformat(),'history_sha256':hashlib.sha256(raw).hexdigest(),'max_age_seconds':max_age_seconds,'limitations':['existing v2 score, not calibrated probability','local clock; no independent timestamp authentication','no v3 decision export or purchase']}
    try:
        captured=capture(day,venue,race,folder/'capture')
        m['capture_relative_path']=str(captured.relative_to(folder))
        entries,distance,going,source=verify_capture(captured)
        cutoff=pd.Timestamp(source['cutoff_at']);receipt=pd.Timestamp(source['snapshot_at'])
        if cutoff.tzinfo is None or receipt.tzinfo is None:raise ValueError('source timezone missing')
        def valid_time():
            t=pd.Timestamp(clock())
            if t.tzinfo is None or t<receipt or t<start:raise ValueError('clock/source ordering invalid')
            if t>=cutoff:raise ValueError('rating not completed before scheduled start')
            if (t-receipt).total_seconds()>max_age_seconds:raise ValueError('odds snapshot too old')
            return t
        valid_time()
        ratings=rate_entries(h,entries,day,venue,race,distance,going)
        generated=valid_time()
        ratings.to_csv(folder/'ratings.csv',index=False,encoding='utf-8-sig')
        entries.to_csv(folder/'verified_entries.csv',index=False,encoding='utf-8-sig')
        # Own schema retains both place prices; never manufacture a single v3 price.
        snapshot=entries.merge(ratings[['馬番','評価点','確かさ(%)','identity_status']],on='馬番',how='left',validate='one_to_one')
        snapshot['race_id']=source['race_id'];snapshot['odds_acquired_at']=receipt.isoformat();snapshot['score_generated_at']=generated.isoformat();snapshot['cutoff_at']=cutoff.isoformat()
        snapshot.to_csv(folder/'scored_snapshot.csv',index=False,encoding='utf-8-sig')
        finished=valid_time()
        m.update(status='completed_prerace',race_id=source['race_id'],cutoff_at=cutoff.isoformat(),score_generated_at=generated.isoformat(),files_written_at=finished.isoformat(),active_runners=int(entries.status.eq('active').sum()),unmatched_runners=int(ratings.identity_status.eq('unmatched').sum()),capture_manifest_sha256=sha(captured/'manifest.json'),files={name:sha(folder/name) for name in ['ratings.csv','verified_entries.csv','scored_snapshot.csv']})
    except Exception as exc:
        m['reason']=f'{type(exc).__name__}: {exc}'
        raise
    finally:(folder/'run_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
    print(ratings[['馬番','馬名','評価点','確かさ(%)','identity_status']].to_string(index=False))
    print('Saved:',folder)
    return folder

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--venue',required=True,choices=VENUES);p.add_argument('--race',required=True,type=int);p.add_argument('--history',default='data/processed/horse_history.csv');p.add_argument('--output',default='data/prerace_runs');p.add_argument('--max-age-seconds',type=int,default=180)
    a=p.parse_args();run(a.venue,a.race,a.history,a.output,a.max_age_seconds)
if __name__=='__main__':main()
