"""Compare calibrators selected on Jan-May only; June-Sept is exploratory evaluation."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from nar_learn_history import features,complete_races,predict,probabilities,metrics


def apply_calibration(p,keys,config):
    p=np.asarray(p,dtype=float)
    if not np.isfinite(p).all() or ((p<=0)|(p>=1)).any():raise ValueError('invalid input probability')
    sums=pd.Series(p).groupby(np.asarray(keys)).sum()
    if not np.allclose(sums,1):raise ValueError('input race probabilities do not sum to 1')
    family=config['family']
    if family=='original':return p.copy()
    if family=='uniform_mixture':
        strength=float(config['strength'])
        if not 0<=strength<=1:raise ValueError('invalid mixture strength')
        counts=pd.Series(np.asarray(keys)).groupby(np.asarray(keys)).transform('size').to_numpy()
        return (1-strength)*p+strength/counts
    if family=='sigmoid_normalized':
        intercept=float(config['intercept']);slope=float(config['slope'])
        if not np.isfinite(intercept) or not np.isfinite(slope) or slope<=0:raise ValueError('invalid sigmoid parameters')
        z=np.clip(intercept+slope*(np.log(p)-np.log1p(-p)),-50,50)
        q=1/(1+np.exp(-z))
        return probabilities(np.log(q),keys)
    raise ValueError('unknown calibrator')


def loss(y,p):
    y=np.asarray(y)
    if not np.isin(y,[0,1]).all() or not (y==1).any():raise ValueError('invalid labels')
    return float(-np.log(np.clip(p[y==1],1e-15,1)).mean())


def choose(cal_p,cal_y,cal_keys):
    configs=[{'family':'original'}]
    configs += [{'family':'uniform_mixture','strength':s} for s in [.05,.1,.2,.3]]
    configs += [{'family':'sigmoid_normalized','intercept':a,'slope':b}
                for a in [-2.,-1.,0.,1.,2.] for b in [.5,.75,1.,1.25,1.5]]
    candidates=[{**c,'calibration_log_loss':loss(cal_y,apply_calibration(cal_p,cal_keys,c))} for c in configs]
    # Stable ordering preserves original calibration on an exact tie.
    best=min(candidates,key=lambda c:c['calibration_log_loss'])
    return best,candidates


def main():
    p=argparse.ArgumentParser();p.add_argument('--history',required=True);p.add_argument('--model',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    model=json.loads(Path(a.model).read_text());m=model['manifest']
    if m['train']!=['2025-01-01','2025-12-31'] or m['calibration']!=['2026-01-01','2026-05-31']:raise ValueError('unexpected chronological split')
    d,_=complete_races(features(pd.read_csv(a.history,low_memory=False)))
    cal=d[d.race_date.between('2026-01-01','2026-05-31')]
    test=d[d.race_date.between('2026-06-01','2026-09-30')].copy()
    if min(cal.race_key.nunique(),test.race_key.nunique())<30:raise ValueError('insufficient chronological samples')
    pc=predict(cal,model,model['temperature']);pt=predict(test,model,model['temperature'])
    selected,trials=choose(pc,cal.won,cal.race_key)
    adjusted=apply_calibration(pt,test.race_key,selected)
    rows=[]
    for name,prob in [('original',pt),('calibration_selected',adjusted)]:
        rows.append({'model':name,'period':'all',**metrics(test,prob)})
        for month,g in test.groupby(test.race_date.dt.strftime('%Y-%m')):
            rows.append({'model':name,'period':month,**metrics(g,prob[test.index.get_indexer(g.index)])})
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(rows).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(trials).to_csv(out/'calibration_trials.csv',index=False,encoding='utf-8-sig')
    test['original_probability']=pt;test['adjusted_probability']=adjusted
    test[['race_date','race_key','horse_key','馬番','won','original_probability','adjusted_probability']].to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig')
    diagnostics=[]
    for name,prob in [('original',pt),('calibration_selected',adjusted)]:
        v=pd.DataFrame({'p':prob,'won':test.won.to_numpy()})
        v['band']=pd.cut(v.p,[0,.02,.05,.1,.2,.4,.6,1],include_lowest=True)
        for band,g in v.groupby('band',observed=True):diagnostics.append({'model':name,'band':str(band),'horses':len(g),'mean_probability':float(g.p.mean()),'win_rate':float(g.won.mean())})
    pd.DataFrame(diagnostics).to_csv(out/'reliability.csv',index=False,encoding='utf-8-sig')
    info={'selected_calibrator':selected,'calibration_races':int(cal.race_key.nunique()),'evaluation_races':int(test.race_key.nunique()),
      'base_model_sha256':hashlib.sha256(Path(a.model).read_bytes()).hexdigest(),'history_sha256':hashlib.sha256(Path(a.history).read_bytes()).hexdigest(),
      'selection':'Jan-May winner log loss only; no evaluation outcomes passed to choose',
      'limitations':['June-Sept has already been inspected in this project; exploratory, not untouched final validation',
      'global calibration does not validate longshot/odds-conditioned profitability','all transforms preserve within-race ordering except numerical ties; no top-rank improvement expected',
      'no EV threshold tuning, no live changes, no revenue claim']}
    (out/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    print('校正期間だけで選択:',selected)
    print(pd.DataFrame(rows).query("period == 'all'").to_string(index=False))
    print('保存先:',out)
if __name__=='__main__':main()
