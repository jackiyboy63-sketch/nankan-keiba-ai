"""Replay a later-trained model on archived pre-race cards/odds. Never a live recommendation."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from nar_learn_history import features,predict


def align_entry_keys(history, entries, day):
    """Only align complete identity when ASCII pedigree spacing is the sole difference."""
    def token(key):
        parts=str(key).split('|')
        if len(parts)!=4 or not all(parts): return None
        return tuple(parts[:2]+[v.replace(' ','') for v in parts[2:]])
    dates=pd.to_datetime(history.race_date,errors='raise')
    keys=set(history.loc[dates.lt(pd.Timestamp(day)),'horse_key'].dropna().astype(str))
    lookup={}
    for key in keys:
        t=token(key)
        if t is not None:lookup.setdefault(t,set()).add(key)
    e=entries.copy();aligned=[]
    for key in e.horse_key:
        if key in keys:aligned.append(key);continue
        matches=lookup.get(token(key),set())
        if len(matches)>1:raise ValueError('空白補正後の馬識別子が一意でないため保留')
        aligned.append(next(iter(matches)) if matches else key)
    e['horse_key']=aligned
    return e


def make_frame(history, entries, day, track, distance, race_id):
    e=entries.copy()
    if e.empty or not {'馬番','horse_key'}.issubset(e): raise ValueError('出走馬不足')
    e=align_entry_keys(history,e,day)
    nums=pd.to_numeric(e['馬番'],errors='coerce')
    if nums.isna().any() or nums.duplicated().any() or nums.le(0).any() or nums.mod(1).ne(0).any(): raise ValueError('馬番不正')
    if e.horse_key.isna().any() or e.horse_key.duplicated().any(): raise ValueError('馬識別子不正')
    if not np.isfinite(float(distance)) or float(distance)<=0: raise ValueError('距離不正')
    h=history.copy();h['race_date']=pd.to_datetime(h.race_date,errors='raise')
    h=h[h.race_date<pd.Timestamp(day)].copy()
    target=pd.DataFrame({'race_date':day,'race_key':race_id,'horse_key':e.horse_key.to_numpy(),
        '馬番':nums.astype(int).to_numpy(),'着順':np.nan,'頭数':len(e),'距離':float(distance),
        'タイム':np.nan,'上がり3F':np.nan,'競馬場':track})
    if h.race_key.eq(race_id).any(): raise ValueError('レース識別子衝突')
    frame=features(pd.concat([h,target],ignore_index=True))
    frame=frame[frame.race_key.eq(race_id)].copy()
    if len(frame)!=len(e) or not frame.prior_starts.gt(0).all(): raise ValueError('全馬の過去走が揃わないためレース全体を保留')
    return frame


def validate_odds(snapshot, numbers, ready, cutoff):
    d=snapshot.copy();d=d[d.status.eq('active')].copy()
    d['馬番']=pd.to_numeric(d['馬番'],errors='raise').astype(int)
    if d['馬番'].duplicated().any() or set(d['馬番'])!=set(numbers): raise ValueError('オッズの馬番不一致')
    o=pd.to_numeric(d.win_odds,errors='coerce')
    t=pd.to_datetime(d.odds_acquired_at,utc=True,errors='coerce')
    c=pd.to_datetime(d.cutoff_at,utc=True,errors='coerce')
    if not np.isfinite(o).all() or o.lt(1).any() or t.isna().any() or c.isna().any(): raise ValueError('オッズ/時刻不足')
    if c.ne(cutoff).any() or t.gt(ready).any() or t.ge(cutoff).any() or (ready-t).dt.total_seconds().gt(180).any(): raise ValueError('オッズの時刻不整合または180秒超過')
    return d[['馬番','win_odds','odds_acquired_at']]


def load_verified(folder):
    from nar_run_store import read_run
    from nar_prerace_rating import verify_capture
    m,data=read_run(folder)
    rel=Path(m['capture_relative_path'])
    if rel.is_absolute() or '..' in rel.parts: raise ValueError('取得パス不正')
    capture=folder/rel
    if hashlib.sha256((capture/'manifest.json').read_bytes()).hexdigest()!=m['capture_manifest_sha256']: raise ValueError('取得記録ハッシュ不一致')
    e,distance,_,s=verify_capture(capture)
    if s['race_id']!=m['race_id']: raise ValueError('レース識別子不一致')
    if not e.status.isin(['active','excluded']).all(): raise ValueError('未対応の出走状態')
    e=e[e.status.eq('active')].copy()
    ts=[pd.Timestamp(x) for x in [m['started_at'],s['snapshot_at'],m['score_generated_at'],m['files_written_at'],s['cutoff_at']]]
    if any(x.tzinfo is None for x in ts) or any(a>b for a,b in zip(ts,ts[1:])) or ts[-2]>=ts[-1]: raise ValueError('発走前の保存時刻不整合')
    if ts[-1]!=pd.Timestamp(m['cutoff_at']): raise ValueError('発走時刻不一致')
    odds=validate_odds(data['scored_snapshot.csv'],e['馬番'],ts[2],ts[-1])
    return m,e,distance,odds


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True);p.add_argument('--history',required=True)
    p.add_argument('--runs',default='data/prerace_runs');p.add_argument('--output',required=True)
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    mraw=Path(a.model).read_bytes();model=json.loads(mraw)
    history=pd.read_csv(a.history,low_memory=False)
    last=max(model['manifest']['train'][1],model['manifest']['calibration'][1])
    candidates=[];skips=[];frames=[];chosen={}
    for path in sorted(Path(a.runs).rglob('run_manifest.json')):
        try:
            m=json.loads(path.read_text())
            if m.get('status')!='completed_prerace':continue
            t=pd.Timestamp(m['files_written_at'])
            if t.tzinfo is None:raise ValueError('保存時刻のタイムゾーンなし')
            candidates.append((t,str(path),m['race_id']))
        except Exception as exc:skips.append({'folder':str(path.parent),'reason':str(exc)})
    for _,path,race_id in sorted(candidates):
        if race_id in chosen:continue
        chosen[race_id]=path
        try:
            folder=Path(path).parent;m,e,distance,odds=load_verified(folder)
            day=race_id[:10]
            if pd.Timestamp(last)>=pd.Timestamp(day):raise ValueError('学習/校正が対象日以降')
            if pd.Timestamp(m['cutoff_at']).tz_convert('Asia/Tokyo').date()!=pd.Timestamp(day).date():raise ValueError('開催日不一致')
            frame=make_frame(history,e,day,m['venue'],distance,race_id)
            frame['win_probability']=predict(frame,model,model['temperature'])
            if not np.isclose(frame.win_probability.sum(),1):raise ValueError('勝率合計不正')
            frame=frame.merge(odds,on='馬番',validate='one_to_one')
            frame['expected_return_ratio']=frame.win_probability*frame.win_odds
            frame['race_id']=race_id;frame['date']=day;frame['cutoff_at']=m['cutoff_at']
            frames.append(frame[['race_id','date','馬番','horse_key','win_probability','win_odds','expected_return_ratio','odds_acquired_at','cutoff_at']])
        except Exception as exc:skips.append({'race_id':race_id,'reason':f'{type(exc).__name__}: {exc}'})
    tickets=[];spent={};decisions=[]
    if frames:
        observations=pd.concat(frames,ignore_index=True)
        observations.to_csv(out/'probabilities.csv',index=False,encoding='utf-8-sig')
        ordered=sorted(observations.groupby('race_id'),key=lambda x:(pd.Timestamp(x[1].cutoff_at.iloc[0]),x[0]))
        for race,g in ordered:
            day=g.date.iloc[0]
            options=g[g.win_odds.ge(10)&g.expected_return_ratio.ge(1.05)]
            reason='期待値またはオッズ条件に未達'
            if not options.empty and spent.get(day,0)+100<=5000:
                b=options.sort_values(['expected_return_ratio','馬番'],ascending=[False,True]).iloc[0]
                tickets.append({**b.to_dict(),'stake_yen':100,'type':'win','status':'retrospective_candidate'})
                spent[day]=spent.get(day,0)+100;reason='再検証の候補あり'
            elif not options.empty:reason='日額上限'
            decisions.append({'race_id':race,'reason':reason})
    pd.DataFrame(tickets).to_csv(out/'candidates.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(decisions).to_csv(out/'decisions.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(skips).to_csv(out/'unavailable.csv',index=False,encoding='utf-8-sig')
    info={'mode':'retrospective_replay_not_live','generated_at':datetime.now(timezone.utc).isoformat(),
      'model_sha256':hashlib.sha256(mraw).hexdigest(),'history_sha256':hashlib.sha256(Path(a.history).read_bytes()).hexdigest(),
      'selected_source_runs':chosen,'input_races':len(chosen),'probability_races':len(frames),'unavailable_records':len(skips),'candidate_races':len(tickets),
      'policy':{'min_win_odds':10,'min_expected_return_ratio':1.05,'stake_yen':100,'daily_cap_yen':5000},
      'limitations':['model created after recorded races; not prospective validation','prior-date historical records may have later corrections; availability not independently proven','odds can change before closing; 5 percent edge is exploratory, not validated','no settlement, ROI claim, automatic purchase or live site changes']}
    (out/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    print('対象',len(chosen),'R / 勝率計算',len(frames),'R / 計算保留',len(skips),'件 / 再検証候補',len(tickets),'R')
    for row in skips:print('保留:',row.get('race_id',row.get('folder')),row['reason'])
    print('保存先:',out)
if __name__=='__main__':main()
