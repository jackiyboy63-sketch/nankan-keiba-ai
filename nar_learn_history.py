"""Retrospective conditional-logit training; no live/EV deployment or odds features."""
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

FEATURES=['form5','win5','clock5','closing5','log_starts','rest_days','distance_change','same_track']

def features(raw):
    d=raw.copy()
    need={'race_date','race_key','horse_key','馬番','着順','頭数','距離','タイム','上がり3F','競馬場'}
    if not need.issubset(d): raise ValueError('missing history columns')
    d['race_date']=pd.to_datetime(d.race_date,errors='raise')
    if d.race_date.isna().any() or d[['horse_key','race_key','馬番']].isna().any().any(): raise ValueError('missing identity/date')
    if d.duplicated(['race_key','馬番']).any() or d.duplicated(['horse_key','race_date']).any(): raise ValueError('duplicate horse/race or same-day start')
    d=d.sort_values(['horse_key','race_date','race_key']).reset_index(drop=True)
    f=pd.to_numeric(d['着順'],errors='coerce'); n=pd.to_numeric(d['頭数'],errors='coerce')
    valid=f.ge(1)&f.le(n)&n.ge(2)&f.mod(1).eq(0)
    d['finish']=f; d['won']=f.eq(1).astype(int)
    d['_form']=((n-f)/(n-1)).where(valid)
    d['_win']=d.won.where(valid)
    packed=pd.to_numeric(d['タイム'],errors='coerce')
    seconds=packed.floordiv(1000)*60+packed.mod(1000)/10
    seconds=seconds.where(packed.gt(0)&packed.mod(1000).lt(600))
    winner=seconds.where(f.eq(1)).groupby(d.race_key).transform('min')
    d['_clock']=(1-(seconds/winner-1)/.12).clip(0,1)
    closing=pd.to_numeric(d['上がり3F'],errors='coerce').where(lambda x:x.gt(0))
    med=closing.groupby(d.race_key).transform('median')
    d['_closing']=(.5+(med-closing)/8).clip(0,1)
    g=d.groupby('horse_key',sort=False)
    for src,dst in [('_form','form5'),('_win','win5'),('_clock','clock5'),('_closing','closing5')]:
        d[dst]=g[src].transform(lambda s:s.shift().rolling(5,min_periods=1).mean())
    d['prior_date']=g.race_date.shift()
    d['prior_starts']=g.cumcount()
    d['log_starts']=np.log1p(d.prior_starts.clip(upper=50))
    d['rest_days']=(d.race_date-d.prior_date).dt.days.clip(upper=365)
    distance=pd.to_numeric(d['距離'],errors='coerce')
    prior_distance=distance.groupby(d.horse_key,sort=False).shift()
    d['distance_change']=(distance-prior_distance).abs()/1000
    prior_track=g['競馬場'].shift()
    d['same_track']=d['競馬場'].eq(prior_track).astype(float).where(d.prior_date.notna())
    return d

def complete_races(d):
    good=[]; excluded=[]
    for key,g in d.groupby('race_key',sort=True):
        n=pd.to_numeric(g['頭数'],errors='coerce')
        ranks=sorted(g.finish.tolist())
        ok=(n.notna().all() and n.nunique()==1 and n.iloc[0]==len(g)
            and ranks==list(range(1,len(g)+1)) and g.won.sum()==1)
        # Exclude entire race if any runner has no historical start; no partial fields.
        if ok and g.prior_starts.gt(0).all(): good.append(key)
        else: excluded.append({'race_key':key,'reason':'incomplete/abnormal results or runner without prior history'})
    return d[d.race_key.isin(good)].copy(),pd.DataFrame(excluded)

def matrix(d, model=None):
    x=d[FEATURES].to_numpy(dtype=float)
    if model is None:
        med=np.array([np.nanmedian(c) if np.isfinite(c).any() else 0 for c in x.T])
        filled=np.where(np.isfinite(x),x,med)
        model={'median':med.tolist(),'mean':filled.mean(0).tolist(),'scale':np.maximum(filled.std(0),1e-6).tolist()}
    missing=~np.isfinite(x)
    z=(np.where(missing,model['median'],x)-model['mean'])/model['scale']
    return np.column_stack([z,missing.astype(float)]),model

def probabilities(logits, keys):
    codes,_=pd.factorize(np.asarray(keys),sort=False)
    maxima=np.full(codes.max()+1,-np.inf);np.maximum.at(maxima,codes,logits)
    e=np.exp(logits-maxima[codes]);den=np.bincount(codes,weights=e)
    return e/den[codes]

def fit(train,steps=400):
    x,prep=matrix(train);y=train.won.to_numpy();keys=train.race_key
    w=np.zeros(x.shape[1]);count=keys.nunique()
    for _ in range(steps):
        p=probabilities(x@w,keys)
        grad=x.T@(p-y)/count+.02*w
        w-=.05*grad
    return {'preprocessing':prep,'weights':w.tolist()}

def predict(d,m,temp=1):
    x,_=matrix(d,m['preprocessing'])
    return probabilities(x@np.array(m['weights'])/temp,d.race_key)

def metrics(d,p):
    f=d.copy();f['probability']=p
    f=f.sort_values(['race_key','probability','馬番'],ascending=[True,False,True])
    leader=f.groupby('race_key',sort=False).head(1)
    brier=f.assign(err=(f.probability-f.won)**2).groupby('race_key').err.sum().mean()
    return {'races':int(f.race_key.nunique()),'horses':len(f),
        'top1_win_pct':float(leader.won.mean()*100),'top1_top3_pct':float(leader.finish.le(3).mean()*100),
        'winner_log_loss':float(-np.log(f.loc[f.won.eq(1),'probability'].clip(lower=1e-15)).mean()),
        'race_brier':float(brier)}

def main():
    a=argparse.ArgumentParser();a.add_argument('--input',default='data/processed/horse_history.csv');a.add_argument('--output',default='learning_results');args=a.parse_args()
    raw=Path(args.input).read_bytes();d=features(pd.read_csv(args.input,low_memory=False))
    d,excluded=complete_races(d)
    # Boundaries and settings fixed before reading the evaluation scores.
    train=d[(d.race_date>='2025-01-01')&(d.race_date<'2026-01-01')]
    cal=d[(d.race_date>='2026-01-01')&(d.race_date<'2026-06-01')]
    test=d[(d.race_date>='2026-06-01')&(d.race_date<'2026-10-01')].copy()
    if any(x.race_key.nunique()<30 for x in [train,cal,test]): raise ValueError('insufficient races in chronological split')
    print('Train/calibration/test races:',*[x.race_key.nunique() for x in [train,cal,test]],flush=True)
    m=fit(train)
    temps=[.5,.75,1.,1.25,1.5,2.,3.]
    temp=min(temps,key=lambda t:metrics(cal,predict(cal,m,t))['winner_log_loss'])
    p=predict(test,m,temp)
    # Simple recent-form control, explicitly NOT existing v1/v2.
    base=probabilities(4*test.form5.fillna(.5).to_numpy(),test.race_key)
    uniform=probabilities(np.zeros(len(test)),test.race_key)
    rows=[]
    for name,prob in [('learned',p),('recent_form_control',base),('uniform_control',uniform)]:
        rows.append({'model':name,'period':'all',**metrics(test,prob)})
        for month,g in test.groupby(test.race_date.dt.strftime('%Y-%m')):
            rows.append({'model':name,'period':month,**metrics(g,prob[test.index.get_indexer(g.index)])})
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    test['predicted_win_probability']=p
    test[['race_date','race_key','horse_key','馬番','finish','won','predicted_win_probability']].to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig')
    summary=pd.DataFrame(rows);summary.to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    excluded.to_csv(out/'excluded.csv',index=False,encoding='utf-8-sig')
    manifest={'input_sha256':hashlib.sha256(raw).hexdigest(),'source_start':str(d.race_date.min().date()),
      'train':['2025-01-01','2025-12-31'],'calibration':['2026-01-01','2026-05-31'],'evaluation':['2026-06-01','2026-09-30'],
      'features':FEATURES,'temperature':temp,'training_races':int(train.race_key.nunique()),'calibration_races':int(cal.race_key.nunique()),
      'limitations':['result-derived entries and final metadata; retrospective, not verified live inputs',
      'no historical pre-race odds; no EV or ROI claims','abnormal/dead-heat races and races with a runner lacking history excluded',
      '2026-06 through 09 previously inspected for v1/v2; not untouched project-level holdout',
      'no rolling retraining; fixed chronological split','not deployed; no automatic purchase']}
    (out/'model.json').write_text(json.dumps({**m,'temperature':temp,'manifest':manifest},ensure_ascii=False,indent=2))
    print(summary.to_string(index=False),flush=True)

if __name__=='__main__':main()
