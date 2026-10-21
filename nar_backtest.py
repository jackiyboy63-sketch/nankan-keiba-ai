"""Batch historical validation for Nankan horse ratings (not live predictions).
Run: python nar_backtest.py --input data/processed/horse_history.csv --month 2026-07 --output-dir backtest_results
"""
import argparse
from pathlib import Path
import pandas as pd
from nar_rating import rating, TRACKS


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data/processed/horse_history.csv')
    p.add_argument('--month', default='2026-07')
    p.add_argument('--output-dir', default='backtest_results')
    p.add_argument('--min-runners', type=int, default=1, help='Use 13 for the prior large-field-only policy')
    p.add_argument('--max-races', type=int, default=0, help='0 means all races; use 10 for a quick test')
    a = p.parse_args()
    df = pd.read_csv(a.input, encoding='utf-8-sig', low_memory=False)
    needed = {'race_date', '競馬場', 'レース番号', 'horse_key', '着順'}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f'Missing columns: {sorted(missing)}')
    dates = pd.to_datetime(df['race_date'], errors='coerce')
    month = pd.Period(a.month, freq='M')
    subset = df.loc[(dates.dt.to_period('M') == month) & df['競馬場'].isin(TRACKS)].copy()
    subset['date_key'] = pd.to_datetime(subset['race_date']).dt.strftime('%Y-%m-%d')
    subset['race_num'] = pd.to_numeric(subset['レース番号'], errors='coerce')
    groups = subset.groupby(['date_key', '競馬場', 'race_num'], dropna=True)
    keys = sorted((date, track, int(race)) for (date, track, race), g in groups if len(g) >= a.min_runners and race >= 1)
    if a.max_races > 0:
        keys = keys[:a.max_races]
    output = Path(a.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows, summaries, failures = [], [], []
    for i, (date, track, race) in enumerate(keys, 1):
        try:
            rated = rating(df, date, track, race).reset_index(drop=True)
            rated['AI順位'] = range(1, len(rated) + 1)
            finish = pd.to_numeric(rated['実際の着順(検証用)'], errors='coerce')
            valid = finish.between(1, len(rated))
            # Do not count invalid/non-finisher labels as a losing prediction.
            if not valid.all() or len(rated) < a.min_runners:
                failures.append({'日付': date, '競馬場': track, 'R': race, '理由': '着順欠測・不正値または出走数不足'})
                continue
            rated.insert(0, '日付', date)
            rated.insert(1, '競馬場', track)
            rated.insert(2, 'R', race)
            rated['3着以内'] = finish.le(3)
            rows.append(rated)
            top = rated.iloc[0]
            top3 = rated.head(3)
            top4 = rated.head(4)
            winner = rated.loc[finish.eq(1)]
            summaries.append({'日付': date, '競馬場': track, 'R': race, '頭数': len(rated),
                              '評価1位勝利': int(finish.iloc[0] == 1),
                              '評価1位3着以内': int(finish.iloc[0] <= 3),
                              '評価上位3頭の3着内頭数': int(top3['3着以内'].sum()),
                              '評価上位4頭の3着内頭数': int(top4['3着以内'].sum()),
                              '勝ち馬AI順位': int(winner['AI順位'].iloc[0]) if len(winner) == 1 else pd.NA,
                              '評価1位の確かさ(%)': top['確かさ(%)']})
        except Exception as exc:
            failures.append({'日付': date, '競馬場': track, 'R': race, '理由': str(exc)[:250]})
        if i % 25 == 0:
            print(f'Processed {i}/{len(keys)}', flush=True)
    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    races = pd.DataFrame(summaries)
    detail.to_csv(output / 'horse_ratings.csv', index=False, encoding='utf-8-sig')
    races.to_csv(output / 'race_summary.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(failures, columns=['日付','競馬場','R','理由']).to_csv(output / 'excluded_races.csv', index=False, encoding='utf-8-sig')
    aggregate = []
    for track, part in [('全場', races)] + [(t, races[races['競馬場'] == t]) for t in sorted(TRACKS)]:
        n = len(part)
        aggregate.append({'競馬場': track, '検証レース数': n,
                          '評価1位勝率(%)': round(100 * part['評価1位勝利'].mean(), 2) if n else None,
                          '評価1位複勝率(%)': round(100 * part['評価1位3着以内'].mean(), 2) if n else None,
                          '上位3頭の3着内捕捉率(%)': round(100 * part['評価上位3頭の3着内頭数'].sum() / (3*n), 2) if n else None,
                          '上位4頭の3着内捕捉率(%)': round(100 * part['評価上位4頭の3着内頭数'].sum() / (3*n), 2) if n else None})
    pd.DataFrame(aggregate).to_csv(output / 'overall_summary.csv', index=False, encoding='utf-8-sig')
    print('Completed:', len(races), 'Excluded:', len(failures), 'Output:', output)

if __name__ == '__main__':
    main()
