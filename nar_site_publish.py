"""Deliver completed pre-race records to the owner's private Site. No purchase.
Credentials are read only from runner secrets and are never written or printed.
"""
import hashlib,json,math,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
import pandas as pd
from nar_capture import VENUES
from nar_prerace_rating import verify_capture
from nar_run_store import read_run

SITE='https://nankan-ai-comparison-20261027.ablecurry7.chatgpt.site'
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def stamp(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None:raise ValueError('timezone missing')
    return t

def optional_number(value):
    if value is None or pd.isna(value):return None
    number=float(value)
    if not math.isfinite(number):raise ValueError('nonfinite numeric value')
    return number

def build_batch(folder,now=None):
    folder=Path(folder);m,data=read_run(folder);relative=Path(m['capture_relative_path'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid capture path')
    capture=folder/relative
    if hashlib.sha256((capture/'manifest.json').read_bytes()).hexdigest()!=m['capture_manifest_sha256']:raise ValueError('capture manifest mismatch')
    entries,_,_,source=verify_capture(capture)
    if source['race_id']!=m['race_id']:raise ValueError('source race mismatch')
    day=m['race_id'][:10];race=int(m['race']);venue=m['venue']
    if m['race_id']!=f'{day}_{VENUES[venue]}_{race:02d}':raise ValueError('race identity mismatch')
    start,receipt,score,finished,cutoff=map(stamp,[m['started_at'],source['snapshot_at'],m['score_generated_at'],m['files_written_at'],m['cutoff_at']])
    if not start<=receipt<=score<=finished<cutoff or cutoff!=stamp(source['cutoff_at']):raise ValueError('not completed before cutoff')
    now=stamp(now if now is not None else datetime.now(timezone.utc))
    if now<finished or now>=cutoff:raise ValueError('not in pre-race delivery window')
    if (now-receipt).total_seconds()>min(180,int(m['max_age_seconds'])):raise ValueError('snapshot stale')
    latest=m.get('history_latest_date')
    if latest and latest>=day:raise ValueError('same-day history')
    active=entries[entries.status.eq('active')].copy()
    if active['馬番'].duplicated().any():raise ValueError('duplicate entries')
    active=active.set_index('馬番');ratings=data['ratings.csv'];horses=[];seen=set()
    for _,r in ratings.iterrows():
        number=int(r['馬番'])
        if number in seen or number not in active.index:raise ValueError('runner mismatch')
        seen.add(number);e=active.loc[number]
        if e['馬名']!=r['馬名']:raise ValueError('horse name mismatch')
        score_value=optional_number(r['評価点'])
        if score_value is not None and r['identity_status']!='matched':raise ValueError('unmatched score')
        state=r.get('評価状態')
        if pd.isna(state) or not state:state='評価可能' if score_value is not None else '評価不能：保存時の理由は未記録'
        horses.append(dict(number=number,name=str(r['馬名']),score=score_value,confidence=optional_number(r['確かさ(%)']),status=state,win_odds=optional_number(e.get('win_odds')),place_odds_low=optional_number(e.get('place_odds_low')),place_odds_high=optional_number(e.get('place_odds_high'))))
    if seen!=set(active.index):raise ValueError('missing runners')
    record=dict(model='existing',date=day,track=venue,race=race,snapshot_at=m['score_generated_at'],race_at=m['cutoff_at'],history_latest_date=latest,odds_at=source['snapshot_at'],source_hash=hashlib.sha256((folder/'run_manifest.json').read_bytes()).hexdigest(),horses=horses,decision={'status':'not_ready','reason':'検証済みの的中確率と買い目生成が未接続のため、買い目は未生成です。見送り判断とは異なります。'})
    return dict(kind='ratings',source='GitHub Actions 発走前評価の即時反映：'+os.environ.get('GITHUB_RUN_ID','実行番号未設定'),records=[record])

def deliver(folder,*,now=None,opener=None,environ=None):
    env=os.environ if environ is None else environ
    url=env.get('NANKAN_SITE_URL','');token=env.get('NANKAN_SITE_TOKEN','')
    if not url and not token:return {'status':'not_configured'}
    if url.rstrip('/')!=SITE or not token or '\n' in token or '\r' in token:raise ValueError('private Site delivery configuration invalid')
    batch=build_batch(folder,now=now);body=json.dumps(batch,ensure_ascii=False,allow_nan=False).encode()
    request=Request(SITE+'/api/records',data=body,headers={'Content-Type':'application/json','OAI-Sites-Authorization':'Bearer '+token},method='POST')
    client=opener if opener is not None else build_opener(NoRedirect())
    with client.open(request,timeout=10) as response:
        result=json.loads(response.read(65536))
    if result.get('count') not in (0,1) or not isinstance(result.get('id'),str):raise ValueError('invalid Site acknowledgement')
    return {'status':'delivered','record_id':result['id'],'race_id':batch['records'][0]['date']+'|'+str(batch['records'][0]['race'])}

def attempt_delivery(folder):
    try:result=deliver(folder)
    except Exception as exc:
        # Never log exception text or headers; preserve capture success independently.
        result={'status':'failed','error_type':type(exc).__name__}
    (Path(folder)/'site_delivery.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('サイトへの反映：'+{'delivered':'完了','not_configured':'未設定','failed':'失敗（評価の保存は継続）'}[result['status']],flush=True)
    return result

def check_connection(environ=None,opener=None):
    env=os.environ if environ is None else environ
    url=env.get('NANKAN_SITE_URL','');token=env.get('NANKAN_SITE_TOKEN','')
    if not url and not token:return False
    if url.rstrip('/')!=SITE or not token or '\n' in token or '\r' in token:raise ValueError('private Site delivery configuration invalid')
    client=opener if opener is not None else build_opener(NoRedirect())
    request=Request(SITE+'/api/records',headers={'OAI-Sites-Authorization':'Bearer '+token})
    with client.open(request,timeout=10) as response:result=json.loads(response.read(1500000))
    if not isinstance(result.get('ratings'),list) or not isinstance(result.get('summaries'),list):raise ValueError('Site readback invalid')
    return True

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    if not a.check:p.error('--check is required')
    try:ok=check_connection()
    except Exception as exc:
        print('サイト接続確認：失敗（'+type(exc).__name__+'）');raise SystemExit(1)
    print('サイト接続確認：'+('成功' if ok else '接続キー未設定'))
