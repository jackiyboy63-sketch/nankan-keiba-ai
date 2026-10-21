"""Nankan baseline ratings. Historical backtest: python nar_rating.py --input data/processed/horse_history.csv --date 2026-07-31 --track 川崎 --race 1 --output ratings.csv
Uses only starts strictly before target date. Target entries from historical results are for testing, NOT live race cards.
"""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

TRACKS = {'大井','船橋','川崎','浦和'}

def number(x):
    return pd.to_numeric(x, errors='coerce')

def time_seconds(x):
    """NAR race time e.g. 1314 -> 1:31.4, 598 -> 0:59.8."""
    if pd.isna(x): return np.nan
    s=str(x).strip().replace('.0','')
    if not s.isdigit(): return np.nan
    v=int(s)
    return (v//1000)*60+(v%1000)/10 if v>=1000 else v/10

def mean_or_nan(s):
    s=pd.to_numeric(s,errors='coerce').dropna()
    return float(s.mean()) if len(s) else np.nan

def rating(df, date, track, race):
    d=df.copy()
    d['race_date']=pd.to_datetime(d['race_date'],errors='coerce')
    d['着順_num']=number(d['着順'])
    d['距離_num']=number(d['距離'])
    d['頭数_num']=number(d['頭数'])
    d['上がり_num']=number(d['上がり3F'])
    d['seconds']=d['タイム'].map(time_seconds)
    target_date=pd.Timestamp(date)
    entries=d[(d.race_date==target_date)&(d['競馬場']==track)&(number(d['レース番号'])==race)].copy()
    if entries.empty: raise ValueError('対象レースが履歴にありません。現在の出走表は別途取り込みが必要です。')
    prior=d[(d.race_date<target_date)&(d.race_date>=target_date-pd.Timedelta(days=730))].copy()
    # Historical labels are deliberately excluded from feature construction.
    result=[]
    distance=number(entries['距離']).dropna().iloc[0]
    for _,e in entries.iterrows():
        h=prior[prior.horse_key==e.horse_key].sort_values('race_date',ascending=False).head(8)
        same=h[(h['競馬場']==track)&((h['距離_num']-distance).abs()<=200)]
        near=h[(h['距離_num']-distance).abs()<=200]
        # Finishing percentile: 1st=1, last=0; missing finish excluded.
        def finish_score(x):
            valid=x[(x['着順_num']>=1)&(x['頭数_num']>=2)&(x['着順_num']<=x['頭数_num'])]
            return mean_or_nan(1-(valid['着順_num']-1)/(valid['頭数_num']-1))
        fit=finish_score(same)
        recent=finish_score(h.head(5))
        # Time relative to own race winner, calculated only using past starts.
        race_min=prior.groupby('race_key')['seconds'].min()
        n=near.copy()
        n['winner_seconds']=n['race_key'].map(race_min)
        n=n[(n.seconds>0)&(n.winner_seconds>0)]
        n['time_score']=(1-(n.seconds/n.winner_seconds-1)/0.12).clip(0,1)
        clock=mean_or_nan(n['time_score'])
        # Closing speed compared only within each past race.
        race_last=prior.groupby('race_key')['上がり_num'].median()
        z=h.copy()
        z['median_last']=z.race_key.map(race_last)
        z=z[(z['上がり_num']>0)&(z.median_last>0)]
        z['last_score']=(0.5+(z.median_last-z['上がり_num'])/8).clip(0,1)
        closing=mean_or_nan(z.last_score)
        # Sire prior starts: weak shrinkage towards neutral, never same/future races.
        sire=prior[(prior['父馬名']==e['父馬名'])&(prior['距離_num'].sub(distance).abs()<=200)]
        sire_perf=finish_score(sire)
        blood=(0.5*30+sire_perf*min(len(sire),30))/(30+min(len(sire),30)) if pd.notna(sire_perf) else np.nan
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
    return pd.DataFrame(result).sort_values(['評価点','確かさ(%)'],ascending=False)

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
