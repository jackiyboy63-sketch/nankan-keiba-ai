"""Fixed-policy chronological validation using official payouts, without odds selection.

Each strategy is an independent 100-yen alternative, with a daily 5,000-yen cap.
No fitting/tuning is performed on the evaluation period. Result-only race cards
cannot prove live profitability. Missing payouts are excluded, never zero-filled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import pandas as pd
from nar_history import load_csv, VENUES, KEY, normalize
from nar_validation import prepare, PreparedHistory, validate_results
from nar_rating import rating as v1
from nar_rating_v2 import rating as v2

POLICIES = ('top1_win', 'top1_place', 'top2_quinella', 'top2_wide')


def load_payouts(root):
    frames = []
    sources = []
    for path in sorted(Path(root).rglob('*.zip')):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if 'payback' not in name.lower() or not name.lower().endswith('.csv'):
                    continue
                d = load_csv(z.read(name))
                d = d[d['競馬場'].isin(VENUES)].copy()
                for c in KEY:
                    d[c] = normalize(d[c])
                d['race_key'] = d[KEY].agg('|'.join, axis=1)
                frames.append(d)
        sources.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if not frames:
        raise ValueError('払戻CSVなし')
    # Keep all distinct rows: dead heats can have more than one payout row.
    return pd.concat(frames, ignore_index=True).drop_duplicates(), sources


def slots(policy):
    if policy == 'top1_win':
        return [(['単勝組番'], '単勝払戻金（円）')]
    if policy == 'top1_place':
        return [([f'複勝組番{i}'], f'複勝払戻金{i}（円）') for i in range(1, 4)]
    if policy == 'top2_quinella':
        return [(['馬複組番1','馬複組番2'], '馬複払戻金（円）')]
    return [([f'ワイド組番{i}馬番1',f'ワイド組番{i}馬番2'], f'ワイド払戻金{i}（円）') for i in range(1, 4)]


def payout(rows, policy, selection):
    found = {}
    for keys, value in slots(policy):
        if not set(keys + [value]).issubset(rows.columns):
            raise ValueError('払戻列不足: ' + policy)
        for _, row in rows.iterrows():
            vals = pd.to_numeric(row[keys + [value]], errors='coerce')
            if vals.isna().all():
                continue
            if vals.isna().any() or (vals <= 0).any() or (vals % 1 != 0).any():
                raise ValueError('払戻データ不正・部分欠損: ' + policy)
            key = tuple(sorted(int(vals[k]) for k in keys))
            amount = int(vals[value])
            if key in found and found[key] != amount:
                raise ValueError('同一組番の払戻が矛盾')
            found[key] = amount
    if not found:
        raise ValueError('払戻データなし: ' + policy)
    return found.get(tuple(sorted(selection)), 0)


def summarize(bets):
    rows = []
    if bets.empty:
        return pd.DataFrame()
    for (model, policy), group in bets.groupby(['model','policy']):
        for period, part in [('all',group)] + list(group.groupby(group['date'].str[:7])):
            part = part.sort_values(['date','track','race'])
            profit = part['return_yen'] - part['stake_yen']
            equity = profit.cumsum()
            # Start from zero so an initial loss counts towards drawdown.
            peak = equity.cummax().clip(lower=0)
            stake, ret = int(part.stake_yen.sum()), int(part.return_yen.sum())
            top = int(part.return_yen.max())
            rows.append(dict(model=model, policy=policy, period=period, bets=len(part),
                             stake_yen=stake, return_yen=ret, profit_yen=ret-stake,
                             roi_pct=round(100*ret/stake,2), hit_pct=round(100*part.return_yen.gt(0).mean(),2),
                             max_drawdown_yen=int((peak-equity).max()), largest_return_yen=top,
                             largest_return_share_pct=round(100*top/ret,2) if ret else 0,
                             roi_without_largest_return_pct=round(100*(ret-top)/stake,2)))
    return pd.DataFrame(rows)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='data/processed/horse_history.csv')
    p.add_argument('--archives',default='.')
    p.add_argument('--start',default='2026-06-01')
    p.add_argument('--end',default='2026-09-30')
    p.add_argument('--output-dir',default='walkforward_results')
    a=p.parse_args()
    history=pd.read_csv(a.input,encoding='utf-8-sig',low_memory=False)
    prepared=PreparedHistory(prepare(history))
    d=prepared.frame
    if pd.Timestamp(a.start) > pd.Timestamp(a.end):
        raise ValueError('開始日が終了日より後')
    target=d[d.race_date.between(a.start,a.end) & d['競馬場'].isin(VENUES)]
    if target.empty:
        raise ValueError('評価期間の対象レースなし')
    pay,sources=load_payouts(a.archives)
    paygroups=dict(tuple(pay.groupby('race_key')))
    bets, accuracy, excluded=[],[],[]
    spent={}
    keys=['race_date','競馬場','レース番号']
    groups=sorted(target.groupby(keys),key=lambda x:(x[0][0],x[0][1],int(x[0][2])))
    for idx,((date,track,race),entries) in enumerate(groups,1):
        day=date.strftime('%Y-%m-%d');race=int(race)
        try:
            validate_results(entries)
        except ValueError as exc:
            excluded.append(dict(date=day,track=track,race=race,stage='entries',reason=str(exc)))
            continue
        labels=dict(zip(pd.to_numeric(entries['馬番']).astype(int), entries['着順_num']))
        payrows=paygroups.get(entries.race_key.iloc[0])
        for model,fn in [('v1',v1),('v2',v2)]:
            rated=fn(prepared,day,track,race).reset_index(drop=True)
            horses=pd.to_numeric(rated['馬番']).astype(int).tolist()
            winner=next(h for h,f in labels.items() if f==1)
            actual_top={h for h,f in labels.items() if f<=3}
            accuracy.append(dict(date=day,track=track,race=race,model=model,runners=len(entries),
                top1_win=int(labels[horses[0]]==1),top1_top3=int(labels[horses[0]]<=3),
                winner_rank=horses.index(winner)+1,top3_captured=len(set(horses[:3])&actual_top),
                actual_top3=len(actual_top),coverage=rated.iloc[0]['確かさ(%)']))
            for policy in POLICIES:
                budget_key=(day,model,policy)
                if spent.get(budget_key,0)+100>5000:
                    excluded.append(dict(date=day,track=track,race=race,model=model,policy=policy,stage='budget',reason='daily cap'))
                    continue
                selection=horses[:1] if policy in POLICIES[:2] else horses[:2]
                try:
                    if len(selection)!=(1 if policy in POLICIES[:2] else 2):
                        raise ValueError('組番に必要な頭数なし')
                    if payrows is None:
                        raise ValueError('対象レース払戻なし')
                    ret=payout(payrows,policy,selection)
                    # Cross-check an apparent payout hit against results; no fabricated misses.
                    should_hit=(labels[selection[0]]==1 if policy=='top1_win' else
                                labels[selection[0]]<=(3 if len(entries)>=8 else 2) if policy=='top1_place' else
                                all(labels[h]<=2 for h in selection) if policy=='top2_quinella' else
                                all(labels[h]<=3 for h in selection))
                    if bool(ret)!=bool(should_hit):
                        raise ValueError('着順と払戻組番が不一致')
                except ValueError as exc:
                    excluded.append(dict(date=day,track=track,race=race,model=model,policy=policy,stage='payout',reason=str(exc)))
                    continue
                spent[budget_key]=spent.get(budget_key,0)+100
                bets.append(dict(date=day,track=track,race=race,model=model,policy=policy,
                                 selection='-'.join(map(str,selection)),stake_yen=100,return_yen=ret))
        if idx%50==0:
            print(f'Processed {idx}/{len(groups)}',flush=True)
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    ledger=pd.DataFrame(bets)
    ledger.to_csv(out/'bets.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(accuracy).to_csv(out/'accuracy.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(excluded).to_csv(out/'excluded.csv',index=False,encoding='utf-8-sig')
    if ledger.empty:
        raise ValueError('有効な購入例なし。excluded.csvを確認してください')
    summary=summarize(ledger);summary.to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    (out/'manifest.json').write_text(json.dumps(dict(start=a.start,end=a.end,policies=POLICIES,
        selection='fixed before result join; each strategy is independent; no odds/popularity',
        input_sha256=hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),archives=sources,
        limitations=['result-derived entries and final going; not live pre-race snapshots',
                     'scratch/DNF/dead-heat/incomplete races excluded; no refund simulation',
                     '100-yen fixed policies; no model fitting, odds threshold or tuning',
                     'no guarantee of 120% annual or future ROI']),ensure_ascii=False,indent=2),encoding='utf-8')
    print(summary.to_string(index=False))
    print('Candidate races:',len(groups),'Accuracy rows:',len(accuracy),'Excluded records:',len(excluded))

if __name__=='__main__':
    main()
