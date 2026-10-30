"""Replay a later-trained model on archived pre-race cards/odds. Never a live recommendation."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from nar_enriched_compare import enriched_features,predict,FEATURES,COURSE,BLOOD,OPPONENT


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
    # Reuse runner/identity/history validation, but rebuild all enriched features.
    from nar_replay_ev import make_frame as base_frame
    base = base_frame(history, entries, day, track, distance, race_id)
    h = history.copy()
    h['race_date'] = pd.to_datetime(h.race_date, errors='raise')
    h = h[h.race_date < pd.Timestamp(day)].copy()
    parents = ['父馬名', '母父馬名']
    if not set(parents).issubset(h):
        raise ValueError('血統列がないため保留')
    target = base[['race_date','race_key','horse_key','馬番','頭数','距離','競馬場']].copy()
    target['距離'] = float(distance)
    # Target result columns are constructed empty, never copied from the card.
    for col in ['着順','タイム','上がり3F']:
        target[col] = np.nan
    latest = h.sort_values('race_date').groupby('horse_key', sort=False).tail(1)
    target = target.merge(latest[['horse_key']+parents], on='horse_key', validate='one_to_one')
    # CSV import may leave distances as strings; group keys must match the card.
    h['距離'] = pd.to_numeric(h['距離'], errors='raise')
    if not np.isfinite(h['距離']).all() or h['距離'].le(0).any():
        raise ValueError('過去走の距離不正')
    frame = enriched_features(pd.concat([h,target], ignore_index=True))
    return frame[frame.race_key.eq(race_id)].copy()


def load_model_bundle(bundle):
    model = bundle['models']['selected']
    cols = model['features']
    supported = FEATURES + COURSE + BLOOD + OPPONENT
    if not cols or len(set(cols)) != len(cols) or any(c not in supported for c in cols):
        raise ValueError('未対応の特徴量')
    if cols != bundle['selected_on_2025']['features']:
        raise ValueError('選択記録とモデルの特徴量が不一致')
    n = len(cols)
    for key, size in [('weights',2*n)]:
        a = np.asarray(model[key], dtype=float)
        if a.shape != (size,) or not np.isfinite(a).all():
            raise ValueError('モデル係数不正')
    for key in ['median','mean','scale']:
        a = np.asarray(model['preprocessing'][key], dtype=float)
        if a.shape != (n,) or not np.isfinite(a).all() or (key == 'scale' and (a <= 0).any()):
            raise ValueError('前処理係数不正')
    temp = float(model['temperature'])
    if not np.isfinite(temp) or temp <= 0:
        raise ValueError('温度不正')
    # Legacy bundle lacks date metadata. This adapter is only for the verified
    # fixed-period producer, and conservatively excludes its full evaluation era.
    return model


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
    mraw=Path(a.model).read_bytes();bundle=json.loads(mraw);model=load_model_bundle(bundle)
    history=pd.read_csv(a.history,low_memory=False)
    last='2026-09-30'  # fixed producer evaluation end; this is retrospective only
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
            if pd.Timestamp(last)>=pd.Timestamp(day):raise ValueError('対象日が固定モデルの学習・校正・既検証期間内')
            if pd.Timestamp(m['cutoff_at']).tz_convert('Asia/Tokyo').date()!=pd.Timestamp(day).date():raise ValueError('開催日不一致')
            frame=make_frame(history,e,day,m['venue'],distance,race_id)
            frame['win_probability']=predict(frame,model,model['temperature'])
            if not np.isfinite(frame.win_probability).all() or not frame.win_probability.between(0,1).all() or not np.isclose(frame.win_probability.sum(),1):raise ValueError('勝率合計不正')
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
      'model_family':'enriched_selected','conservative_exclusion_end':'2026-09-30',
      'model_sha256':hashlib.sha256(mraw).hexdigest(),'history_sha256':hashlib.sha256(Path(a.history).read_bytes()).hexdigest(),
      'selected_source_runs':chosen,'input_races':len(chosen),'probability_races':len(frames),'unavailable_records':len(skips),'candidate_races':len(tickets),
      'goals':{'lifetime_roi_pct':120,'hit_return_pct':500,'guaranteed':False},
      'policy':{'min_win_odds':10,'min_expected_return_ratio':1.05,'stake_yen':100,'daily_cap_yen':5000},
      'limitations':['model created after recorded races; not prospective validation','only fixed-period nar_enriched_compare.py bundles supported; not a general model loader','evaluation through September has been inspected; replay only after 2026-09-30','100 yen is a comparison stake, not a reinstated per-race investment cap','prior-date historical records may have later corrections; availability not independently proven','odds can change before closing; 5 percent edge is exploratory, not validated','no settlement, ROI claim, automatic purchase or live site changes']}
    (out/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    print('対象',len(chosen),'R / 勝率計算',len(frames),'R / 計算保留',len(skips),'件 / 再検証候補',len(tickets),'R')
    for row in skips:print('保留:',row.get('race_id',row.get('folder')),row['reason'])
    print('保存先:',out)
if __name__=='__main__':main()

