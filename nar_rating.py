"""Nankan baseline ratings. Historical backtest: python nar_rating.py --input data/processed/horse_history.csv --date 2026-07-31 --track 川崎 --race 1 --output ratings.csv
Uses only starts strictly before target date. Target entries from historical results are for testing, NOT live race cards.
"""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from nar_validation import prepare, validate_entries, parse_seconds

TRACKS = {'大井','船橋','川崎','浦和'}

def number(x):
    return pd.to_numeric(x, errors='coerce')

def time_seconds(x):
    return parse_seconds(x)

def mean_or_nan(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    return float(s.mean()) if len(s) else np.nan

def rating(df, date, track, race):
    d=prepare(df)
    target_date=pd.Timestamp(date)
    entries=d[(d.race_date==target_date)&(d['競馬場']==track)&(number(d['レース番号'])==race)].copy()
    validate_entries(entries)
    prior=d[(d.race_date<target_date)&(d.race_date>=target_date-pd.Timedelta(days=730))].copy()
    # Historical labels are deliberately excluded from feature construction.
    # Race entries on the target date are only used for horse identity, track and distance.
    result=[]
    distances=number(entries['距離']).dropna()
    if distances.empty: raise ValueError('対象レースの距離が取得できません。')
    distance=distances.iloc[0]
    race_min=prior[prior['着順_num'].eq(1)].groupby('race_key')['seconds'].min()
    race_last=prior.loc[prior['上がり_num'].gt(0)].groupby('race_key')['上がり_num'].median()
    for _,e in entries.iterrows():
        h=prior[prior.horse_key==e.horse_key].sort_values('race_date',ascending=False).head(8)
        same=h[(h['競馬場']==track)&(h['距離_num']==distance)]
        near=h[(h['距離_num']==distance)]
        # Finishing percentile: 1st=1, last=0; missing finish excluded.
        def finish_score(x):
            valid=x[(x['着順_num']>=1)&(x['頭数_num']>=2)&(x['着順_num']<=x['頭数_num'])]
            return mean_or_nan(1-(valid['着順_num']-1)/(valid['頭数_num']-1))
        fit=finish_score(same)
        recent=finish_score(h.head(5))
        # Time relative to own race winner, calculated only using past starts.
        n=near.copy()
        n['winner_seconds']=n['race_key'].map(race_min)
        n=n[(n.seconds>0)&(n.winner_seconds>0)]
        n['time_score']=(1-(n.seconds/n.winner_seconds-1)/0.12).clip(0,1)
        clock=mean_or_nan(n['time_score'])
        # Closing speed compared only within each past race.
        z=h.copy()
        z['median_last']=z.race_key.map(race_last)
        z=z[(z['上がり_num']>0)&(z.median_last>0)]
        z['last_score']=(0.5+(z.median_last-z['上がり_num'])/8).clip(0,1)
        closing=mean_or_nan(z.last_score)
        # Sire prior starts: weak shrinkage towards neutral, never same/future races.
        sire=prior[(prior['父馬名']==e['父馬名'])&(prior['競馬場']==track)&(prior['距離_num']==distance)]
        sire_perf=finish_score(sire)
        sire_valid=sire[(sire['着順_num']>=1)&(sire['頭数_num']>=2)&(sire['着順_num']<=sire['頭数_num'])]
        blood=(0.5*30+sire_perf*len(sire_valid))/(30+len(sire_valid)) if pd.notna(sire_perf) and len(sire_valid)>=10 and sire_valid['horse_key'].nunique()>=3 else np.nan
        stability=np.nan
        if len(h)>=3:
            f=h[(h['着順_num']>=1)&(h['頭数_num']>=2)&(h['着順_num']<=h['頭数_num'])]
            if len(f)>=3:
                v=1-(f['着順_num']-1)/(f['頭数_num']-1)
                stability=float((1-v.std(ddof=0)).clip(0,1))
        vals=[fit,recent,clock,closing,blood,stability]
        weights=[25,25,20,15,10,5]
        available=sum(w for w,v in zip(weights,vals) if pd.notna(v))
        # Neutral imputation and separately reported coverage; no inflated score on missing data.
        score=sum(w*(v if pd.notna(v) else 0.5) for w,v in zip(weights,vals))
        result.append({'馬番':e['馬番'],'馬名':e['馬名'],'評価点':round(score,1),'確かさ(%)':available,
                       '過去走数':len(h),'コース距離':fit,'近走':recent,'時計':clock,'末脚':closing,'血統':blood,'安定性':stability,
                       '実際の着順(検証用)':e['着順']})
    return pd.DataFrame(result).assign(_tie=lambda x: pd.to_numeric(x['馬番'])).sort_values(['評価点','確かさ(%)','_tie'],ascending=[False,False,True]).drop(columns='_tie')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='data/processed/horse_history.csv')
    p.add_argument('--date',required=True)
    p.add_argument('--track',required=True,choices=sorted(TRACKS))
    p.add_argument('--race',required=True,type=int)
    p.add_argument('--output',default='ratings.csv')
    a=p.parse_args()
    df=pd.read_csv(a.input,encoding='utf-8-sig',low_memory=False)
    out=rating(df,a.date,a.track,a.race)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(a.output,index=False,encoding='utf-8-sig')
    print(out[['馬番','馬名','評価点','確かさ(%)','過去走数']].to_string(index=False))
    print('Saved:',a.output)
if __name__=='__main__': main()
