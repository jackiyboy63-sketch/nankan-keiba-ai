"""Pre-race-only decision engine. No betting until timestamped snapshots and calibration exist."""
from __future__ import annotations
import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

REQUIRED = {'race_id','horse_no','snapshot_at','cutoff_at','score','win_odds','place_odds','source'}


def parse_time(s):
    x = pd.to_datetime(s, utc=True, errors='coerce')
    if pd.isna(x): raise ValueError('invalid timestamp')
    return x


def validate_snapshot(df):
    missing = REQUIRED - set(df.columns)
    if missing: raise ValueError('missing snapshot columns: '+','.join(sorted(missing)))
    if df.empty: raise ValueError('empty snapshot')
    if df[['race_id','horse_no']].isna().any().any() or df.duplicated(['race_id','horse_no']).any():
        raise ValueError('missing or duplicated runners')
    d=df.copy()
    for col in ['snapshot_at','cutoff_at']:
        if not d[col].astype(str).str.contains(r'(?:Z|[+-]\d{2}:\d{2})$', regex=True).all():
            raise ValueError('timestamps must include timezone')
    for col in ['snapshot_at','cutoff_at']:
        d[col]=pd.to_datetime(d[col],utc=True,errors='coerce')
    if d[['snapshot_at','cutoff_at']].isna().any().any() or (d.snapshot_at >= d.cutoff_at).any():
        raise ValueError('snapshot not strictly before cutoff')
    for col in ['score','win_odds','place_odds']:
        d[col]=pd.to_numeric(d[col],errors='coerce')
    if d[['score','win_odds','place_odds']].isna().any().any() or not np.isfinite(d[['score','win_odds','place_odds']].to_numpy()).all():
        raise ValueError('invalid score/odds')
    if (d[['win_odds','place_odds']] < 1).any().any(): raise ValueError('odds below 1')
    if d.source.astype(str).str.strip().eq('').any(): raise ValueError('missing source')
    if d.groupby('race_id')['cutoff_at'].nunique().gt(1).any(): raise ValueError('inconsistent cutoff')
    return d


def fit_calibration(training, *, label='won', min_races=30, alpha=10):
    """Empirical-Bayes score-quantile calibration; strictly training-only, no target labels."""
    need={'race_id','score',label,'race_date'}
    if not need.issubset(training): raise ValueError('missing training columns')
    d=training.copy()
    d['score']=pd.to_numeric(d.score,errors='coerce')
    d[label]=pd.to_numeric(d[label],errors='coerce')
    if d[['score',label]].isna().any().any() or not d[label].isin([0,1]).all(): raise ValueError('invalid labels')
    if d.race_id.nunique()<min_races: raise ValueError('insufficient training races')
    # Train score-bin cutoffs once; never fit on evaluation observations.
    edges=np.unique(np.quantile(d.score,np.linspace(0,1,6)))
    if len(edges)<2: raise ValueError('constant scores')
    bins=np.searchsorted(edges[1:-1],d.score,side='right')
    prior=float(d[label].mean())
    rates=[]
    for i in range(len(edges)-1):
        y=d.loc[bins==i,label]
        rates.append(float((y.sum()+alpha*prior)/(len(y)+alpha)))
    return {'edges':edges.tolist(),'rates':rates,'label':label,'training_end':str(pd.to_datetime(d.race_date).max().date()),'races':int(d.race_id.nunique())}


def calibrated_probability(scores, model):
    x=pd.to_numeric(scores,errors='coerce').to_numpy(dtype=float)
    if not np.isfinite(x).all(): raise ValueError('nonfinite scores')
    return np.array(model['rates'])[np.searchsorted(model['edges'][1:-1],x,side='right')]


def decide(snapshot, calibration, *, as_of, daily_cap=5000, min_edge=0.05, stake=100, already_spent=0):
    """Conservative single-horse win/place EV selection. No calibrated model => no bet."""
    d=validate_snapshot(snapshot)
    now=parse_time(as_of)
    if (d.snapshot_at > now).any() or (d.cutoff_at <= now).any(): raise ValueError('as_of outside valid pre-race window')
    if calibration is None: return pd.DataFrame(columns=['race_id','horse_no','type','probability','odds','edge','stake_yen','reason'])
    if any(pd.Timestamp(m['training_end'],tz='UTC') >= d.snapshot_at.min() for m in calibration.values() if m):
        raise ValueError('calibration overlaps prediction period')
    if not (0<=already_spent<=daily_cap): raise ValueError('invalid budget')
    remaining=daily_cap-already_spent
    if remaining<stake: return pd.DataFrame(columns=['race_id','horse_no','type','probability','odds','edge','stake_yen','reason'])
    # Only one ticket per race; no fabricated pair probabilities.
    candidates=[]
    for race, g in d.groupby('race_id',sort=True):
        for kind, col, model_key in [('win','win_odds','win'),('place','place_odds','place')]:
            model=calibration.get(model_key)
            if not model: continue
            p=calibrated_probability(g.score,model)
            for (_,row),prob in zip(g.iterrows(),p):
                edge=float(prob*row[col]-1)
                if edge>=min_edge:
                    candidates.append(dict(race_id=race,horse_no=row.horse_no,type=kind,probability=round(float(prob),6),odds=float(row[col]),edge=round(edge,6),stake_yen=stake,reason='calibrated_positive_ev'))
    result=[]
    for race in sorted(d.race_id.unique()):
        options=[x for x in candidates if x['race_id']==race]
        if options and remaining>=stake:
            best=sorted(options,key=lambda x:(-x['edge'],str(x['horse_no']),x['type']))[0]
            result.append(best);remaining-=stake
    return pd.DataFrame(result,columns=['race_id','horse_no','type','probability','odds','edge','stake_yen','reason'])


def walk_forward(snapshots, results, *, min_train_races=30, daily_cap=5000, min_edge=0.05):
    """Strict chronological evaluation; result join only AFTER predictions are frozen."""
    s=validate_snapshot(snapshots)
    needed={'race_id','horse_no','race_date','won','placed','win_return_100','place_return_100'}
    if not needed.issubset(results): raise ValueError('missing result columns')
    r=results.copy()
    if r.duplicated(['race_id','horse_no']).any(): raise ValueError('duplicate result keys')
    for c in ['won','placed']:
        if not pd.to_numeric(r[c],errors='coerce').isin([0,1]).all(): raise ValueError('invalid result labels')
    if not set(s.race_id).issubset(set(r.race_id)): raise ValueError('missing result races')
    s=s.merge(r[['race_id','horse_no','race_date']],on=['race_id','horse_no'],validate='one_to_one')
    s['race_date']=pd.to_datetime(s.race_date).dt.date
    if s.groupby('race_id').race_date.nunique().gt(1).any(): raise ValueError('inconsistent race dates')
    ledger=[];skips=[]
    for day in sorted(s.race_date.unique()):
        train=r[pd.to_datetime(r.race_date).dt.date<day].merge(snapshots[['race_id','horse_no','score']],on=['race_id','horse_no'],how='inner',validate='one_to_one')
        if train.race_id.nunique()<min_train_races:
            skips.append({'date':str(day),'reason':'insufficient prior training races'});continue
        try:
            models={'win':fit_calibration(train.rename(columns={'won':'label'}),label='label',min_races=min_train_races),
                    'place':fit_calibration(train.rename(columns={'placed':'label'}),label='label',min_races=min_train_races)}
        except ValueError as e:
            skips.append({'date':str(day),'reason':str(e)});continue
        day_snap=s[s.race_date==day]
        # Each race uses its latest stored snapshot time as simulated decision instant.
        spent=0
        for race,g in day_snap.groupby('race_id',sort=True):
            try:
                chosen=decide(g,models,as_of=g.snapshot_at.max(),daily_cap=daily_cap,min_edge=min_edge,already_spent=spent)
            except ValueError as e:
                skips.append({'date':str(day),'race_id':race,'reason':str(e)});continue
            if chosen.empty: continue
            frozen=chosen.merge(r,on=['race_id','horse_no'],validate='one_to_one')
            for _,b in frozen.iterrows():
                ret=b['win_return_100'] if b['type']=='win' else b['place_return_100']
                if pd.isna(ret) or float(ret)<0: raise ValueError('missing/invalid payout: '+str(race))
                ledger.append({**{k:b[k] for k in ['race_id','horse_no','type','probability','odds','edge','stake_yen']},'date':str(day),'return_yen':float(ret)})
                spent+=int(b.stake_yen)
    return pd.DataFrame(ledger),pd.DataFrame(skips)


def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshots',required=True);p.add_argument('--results',required=True);p.add_argument('--output-dir',default='v3_results');p.add_argument('--min-train-races',type=int,default=30)
    a=p.parse_args();out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    bets,skips=walk_forward(pd.read_csv(a.snapshots),pd.read_csv(a.results),min_train_races=a.min_train_races)
    bets.to_csv(out/'bets.csv',index=False);skips.to_csv(out/'skips.csv',index=False)
    summary={'bets':len(bets),'stake_yen':float(bets.stake_yen.sum()) if not bets.empty else 0,'return_yen':float(bets.return_yen.sum()) if not bets.empty else 0}
    summary['roi_pct']=100*summary['return_yen']/summary['stake_yen'] if summary['stake_yen'] else None
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(summary)
if __name__=='__main__':main()
