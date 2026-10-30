"""Select added historical features on 2025 validation, then calibrate and evaluate later."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from nar_learn_history import features,complete_races,probabilities,metrics,FEATURES
COURSE=['course_form','course_starts','distance_form','distance_starts']
BLOOD=['sire_course_form','damsire_course_form']
OPPONENT=['past_opponent_form']

def enriched_features(raw):
    d=features(raw)
    groups=[('course',['horse_key','競馬場','距離']),('distance',['horse_key','距離'])]
    for name,keys in groups:
        g=d.groupby(keys,sort=False,dropna=False)
        d[name+'_form']=g['_form'].transform(lambda x:x.shift().rolling(8,min_periods=1).mean())
        d[name+'_starts']=np.log1p(g.cumcount().clip(upper=30))
    # Past competitors' form as known before their race, then lag to this horse's next start.
    observed=d.form5.notna().astype(int)
    total=d.form5.fillna(0).groupby(d.race_key).transform('sum')
    count=observed.groupby(d.race_key).transform('sum')-observed
    d['_opponent']=(total-d.form5.fillna(0))/count.where(count.gt(0))
    d['past_opponent_form']=d.groupby('horse_key',sort=False)['_opponent'].transform(lambda x:x.shift().rolling(5,min_periods=1).mean())
    for parent,label in [('父馬名','sire_course_form'),('母父馬名','damsire_course_form')]:
        keys=[parent,'競馬場','距離'];valid=d[d[parent].notna()&d[parent].astype(str).str.strip().ne('')&d._form.notna()].copy()
        first=valid.groupby(keys+['horse_key'],dropna=False).race_date.transform('min')
        valid['_new_horse']=valid.race_date.eq(first).astype(int)
        daily=valid.groupby(keys+['race_date'],as_index=False).agg(total=('_form','sum'),starts=('_form','size'),offspring=('_new_horse','sum'))
        daily=daily.sort_values(keys+['race_date'])
        for col in ['total','starts','offspring']:
            daily['prior_'+col]=daily.groupby(keys,dropna=False)[col].cumsum()-daily[col]
        # Query days may contain no eligible result. Use prior cumulative end-of-day totals strictly earlier than query day.
        lookup={}
        for k,g in daily.groupby(keys,dropna=False):
            lookup[k]=(g.race_date.to_numpy(),np.column_stack([g.prior_total+g.total,g.prior_starts+g.starts,g.prior_offspring+g.offspring]))
        vals=np.full(len(d),np.nan)
        for k,g in d.groupby(keys,dropna=False):
            if k not in lookup:continue
            dates,acc=lookup[k];idx=np.searchsorted(dates,g.race_date.to_numpy(),side='left')-1
            ok=idx>=0
            if not ok.any():continue
            v=acc[idx[ok]];support=(v[:,1]>=10)&(v[:,2]>=3)
            scores=(v[:,0]+15)/(v[:,1]+30)
            vals[g.index.to_numpy()[ok][support]]=scores[support]
        d[label]=vals
    return d


def matrix(d,cols,prep=None):
    x=d[cols].to_numpy(float);missing=~np.isfinite(x)
    if prep is None:
        median=np.array([np.nanmedian(c) if np.isfinite(c).any() else 0 for c in x.T]);f=np.where(missing,median,x)
        prep={'median':median.tolist(),'mean':f.mean(0).tolist(),'scale':np.maximum(f.std(0),1e-6).tolist()}
    z=(np.where(missing,prep['median'],x)-prep['mean'])/prep['scale']
    return np.column_stack([z,missing.astype(float)]),prep

def fit(d,cols,ridge):
    x,prep=matrix(d,cols);y=d.won.to_numpy();w=np.zeros(x.shape[1]);n=d.race_key.nunique()
    for _ in range(400):
        p=probabilities(x@w,d.race_key);w-=.05*(x.T@(p-y)/n+ridge*w)
    return {'features':cols,'ridge':ridge,'weights':w.tolist(),'preprocessing':prep}

def predict(d,model,temp=1):
    x,_=matrix(d,model['features'],model['preprocessing'])
    return probabilities(x@np.array(model['weights'])/temp,d.race_key)

def main():
    p=argparse.ArgumentParser();p.add_argument('--history',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    raw=pd.read_csv(a.history,low_memory=False);d,_=complete_races(enriched_features(raw))
    train=d[d.race_date.between('2025-01-01','2025-08-31')]
    validation=d[d.race_date.between('2025-09-01','2025-12-31')]
    full=d[d.race_date.between('2025-01-01','2025-12-31')]
    cal=d[d.race_date.between('2026-01-01','2026-05-31')]
    test=d[d.race_date.between('2026-06-01','2026-09-30')].copy()
    if min(x.race_key.nunique() for x in [train,validation,cal,test])<30:raise ValueError('insufficient chronological sample')
    sets=[('base',FEATURES),('course_blood',FEATURES+COURSE+BLOOD),('course_blood_opponents',FEATURES+COURSE+BLOOD+OPPONENT)]
    trials=[]
    for name,cols in sets:
        for ridge in [.02,.1]:
            m=fit(train,cols,ridge);score=metrics(validation,predict(validation,m))['winner_log_loss']
            trials.append({'name':name,'features':cols,'ridge':ridge,'validation_log_loss':score})
            print('2025 validation:',name,ridge,round(score,6),flush=True)
    selected=min(trials,key=lambda x:x['validation_log_loss'])
    models={'base':fit(full,FEATURES,.02),'selected':fit(full,selected['features'],selected['ridge'])}
    rows=[];predictions=[]
    for name,m in models.items():
        temp=min([.5,.75,1.,1.25,1.5,2.,3.],key=lambda t:metrics(cal,predict(cal,m,t))['winner_log_loss'])
        m['temperature']=temp;prob=predict(test,m,temp)
        rows.append({'model':name,'period':'all',**metrics(test,prob)})
        for month,g in test.groupby(test.race_date.dt.strftime('%Y-%m')):
            rows.append({'model':name,'period':month,**metrics(g,prob[test.index.get_indexer(g.index)])})
        f=test[['race_date','race_key','horse_key','馬番','won','finish']].copy();f['model']=name;f['probability']=prob;predictions.append(f)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(trials).to_csv(out/'validation_trials.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(rows).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    pd.concat(predictions).to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig')
    info={'selected_on_2025':selected,'models':models,'history_sha256':hashlib.sha256(Path(a.history).read_bytes()).hexdigest(),
      'races':{k:int(v.race_key.nunique()) for k,v in [('train',train),('validation',validation),('calibration',cal),('evaluation',test)]},
      'limitations':['result-derived entries, not independently verified historical live inputs','June-Sept repeatedly inspected; exploratory, final future-period validation required','bloodline support: at least 10 prior starts and 3 offspring, same track and exact distance','opponent form is past relative finish form, not verified race class','no ROI or EV threshold tuning, no live model replacement']}
    (out/'models.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    print('2025だけで選択:',selected)
    print(pd.DataFrame(rows).query("period=='all'").to_string(index=False));print('保存先:',out)
if __name__=='__main__':main()
