"""南関東・過去データ専用評価 v2。評価対象日の着順・時計は特徴量に使用しない。
例: python nar_rating_v2.py --input horse_history.csv --date 2026-07-31 --track 川崎 --race 1 --output ratings_v2.csv
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

TRACKS = {'大井', '船橋', '川崎', '浦和'}
WEIGHTS = {'適性':25, '近走':25, '時計':20, '末脚':15, '血統':10, '安定性':5}

def avg(x):
    x = pd.to_numeric(pd.Series(x), errors='coerce').dropna()
    return float(x.mean()) if len(x) else np.nan

def finish(x):
    x = x[(x['着順_num'] >= 1) & (x['頭数_num'] >= 2) & (x['着順_num'] <= x['頭数_num'])]
    return avg(1 - (x['着順_num']-1)/(x['頭数_num']-1))

def seconds(x):
    if pd.isna(x): return np.nan
    s = str(x).strip()
    if s.endswith('.0'): s=s[:-2]
    if not s.isdigit(): return np.nan
    n = int(s)
    return (n//1000)*60+(n%1000)/10 if n >= 1000 else n/10

def rating(df, date, track, race):
    required = {'race_date','着順','距離','頭数','上がり3F','タイム','競馬場','レース番号',
                'horse_key','race_key','父馬名','母父馬名','馬番','馬名','馬場'}
    missing = required-set(df.columns)
    if missing: raise ValueError('不足列: '+', '.join(sorted(missing)))
    d=df.copy()
    d['race_date']=pd.to_datetime(d['race_date'],errors='coerce')
    for col,new in [('着順','着順_num'),('距離','距離_num'),('頭数','頭数_num'),('上がり3F','上がり_num')]:
        d[new]=pd.to_numeric(d[col],errors='coerce')
    d['seconds']=d['タイム'].map(seconds)
    target=pd.Timestamp(date)
    entries=d[(d.race_date==target)&(d['競馬場']==track)&(pd.to_numeric(d['レース番号'],errors='coerce')==race)].copy()
    if entries.empty: raise ValueError('対象レースなし。過去結果を使うバックテスト専用です。')
    distance=entries['距離_num'].dropna()
    if distance.empty: raise ValueError('対象距離なし')
    distance=distance.iloc[0]
    surface=entries['馬場'].dropna().iloc[0] if entries['馬場'].notna().any() else None
    prior=d[(d.race_date<target)&(d.race_date>=target-pd.Timedelta(days=730))].copy()
    # レース内基準は過去レースのみ。勝ち馬の時計が欠測なら時計指標は欠測。
    winners=prior[prior['着順_num']==1].groupby('race_key')['seconds'].min()
    med_last=prior.groupby('race_key')['上がり_num'].median()
    results=[]
    for _,e in entries.iterrows():
        h=prior[prior.horse_key==e.horse_key].sort_values('race_date',ascending=False).head(8)
        same=h[(h['競馬場']==track)&(h['距離_num']==distance)]
        same_surface=same[same['馬場']==surface] if surface is not None else same.iloc[:0]
        # 同馬場の実績があれば優先、なければ同コース・同距離に後退。
        fit=finish(same_surface) if len(same_surface)>=2 else finish(same)
        recent=finish(h.head(5))
        near=h[h['距離_num']==distance].copy()
        near['winner']=near['race_key'].map(winners)
        near=near[(near.seconds>0)&(near.winner>0)]
        near['relative']=(1-(near.seconds/near.winner-1)/0.12).clip(0,1)
        clock=avg(near['relative'])
        z=h.copy()
        z['race_median']=z.race_key.map(med_last)
        z=z[(z['上がり_num']>0)&(z.race_median>0)]
        closing=avg((0.5+(z.race_median-z['上がり_num'])/8).clip(0,1))
        # 父・母父の同場同距離産駒実績。本人の過去走も含むが未来走は除外。
        blood_parts=[]
        for col,weight in [('父馬名',0.7),('母父馬名',0.3)]:
            if pd.isna(e[col]): continue
            s=prior[(prior[col]==e[col])&(prior['競馬場']==track)&(prior['距離_num']==distance)]
            valid=s[(s['着順_num']>=1)&(s['頭数_num']>=2)&(s['着順_num']<=s['頭数_num'])]
            if len(valid)>=10 and valid.horse_key.nunique()>=3:
                perf=finish(valid)
                blood_parts.append((weight,(15+len(valid)*perf)/(30+len(valid))))
        blood=sum(w*v for w,v in blood_parts)/sum(w for w,_ in blood_parts) if blood_parts else np.nan
        valid=h[(h['着順_num']>=1)&(h['頭数_num']>=2)&(h['着順_num']<=h['頭数_num'])]
        v=1-(valid['着順_num']-1)/(valid['頭数_num']-1)
        stability=float(np.clip(1-v.std(ddof=0),0,1)) if len(v)>=3 else np.nan
        vals=dict(zip(WEIGHTS,[fit,recent,clock,closing,blood,stability]))
        coverage=sum(WEIGHTS[k] for k,v in vals.items() if pd.notna(v))
        score=sum(WEIGHTS[k]*(v if pd.notna(v) else 0.5) for k,v in vals.items())
        results.append({'馬番':e['馬番'],'馬名':e['馬名'],'評価点':round(score,2),'確かさ(%)':coverage,
                        '過去走数':len(h),**vals,'実際の着順(検証用)':e['着順']})
    return pd.DataFrame(results).sort_values(['評価点','確かさ(%)'],ascending=False)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='horse_history.csv')
    p.add_argument('--date',required=True)
    p.add_argument('--track',required=True,choices=sorted(TRACKS))
    p.add_argument('--race',required=True,type=int)
    p.add_argument('--output',default='ratings_v2.csv')
    a=p.parse_args()
    d=pd.read_csv(a.input,encoding='utf-8-sig',low_memory=False)
    out=rating(d,a.date,a.track,a.race)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(a.output,index=False,encoding='utf-8-sig')
    print(out[['馬番','馬名','評価点','確かさ(%)','過去走数']].to_string(index=False))
    print('Saved:',a.output)
if __name__=='__main__': main()
