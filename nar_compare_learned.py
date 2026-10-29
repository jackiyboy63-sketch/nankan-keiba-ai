from pathlib import Path
import pandas as pd
from nar_validation import PreparedHistory, prepare
from nar_rating_v2 import rating
from nar_learn_history import features,complete_races,metrics
import argparse
a=argparse.ArgumentParser();a.add_argument('--input',default='data/processed/horse_history.csv');a.add_argument('--results',default='learning_results/initial-20261029');args=a.parse_args()
raw=pd.read_csv(args.input,low_memory=False)
d,_=complete_races(features(raw))
test=d[(d.race_date>='2026-06-01')&(d.race_date<'2026-10-01')].copy()
h=PreparedHistory(prepare(raw))
rows=[]
for i,(key,g) in enumerate(test.groupby('race_key'),1):
 r=rating(h,g.race_date.iloc[0],g['競馬場'].iloc[0],int(g['レース番号'].iloc[0]))
 nos=pd.to_numeric(r['馬番']).astype(int).tolist();labels=dict(zip(pd.to_numeric(g['馬番']).astype(int),g.finish))
 actual={n for n,f in labels.items() if f<=3}
 rows.append(dict(race_key=key,date=str(g.race_date.iloc[0].date()),winner=int(labels[nos[0]]==1),top3=int(labels[nos[0]]<=3),captured=len(set(nos[:3])&actual)))
 if i%100==0: print('Compared existing v2:',i,flush=True)
pd.DataFrame(rows).to_csv(Path(args.results)/'existing_v2_same_races.csv',index=False)
print(pd.DataFrame(rows)[['winner','top3','captured']].mean().to_dict(),flush=True)
