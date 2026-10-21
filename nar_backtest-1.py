"""Historical validation for Nankan ratings; no future results used for features.

Example: python nar_backtest.py --input data/processed/horse_history.csv --month 2026-06 --output-dir backtest_results
"""
import argparse
from pathlib import Path
import pandas as pd
from nar_rating import rating, TRACKS


def classify_finish(series, n):
    """Return valid finish mask and specific issue per entry."""
    numeric = pd.to_numeric(series, errors='coerce')
    labels = series.astype('string').str.strip()
    missing = series.isna() | labels.eq('').fillna(False)
    invalid = numeric.isna() & ~missing
    out_of_range = numeric.notna() & (~numeric.between(1, n) | (numeric % 1 != 0))
    return numeric, missing, invalid, out_of_range


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data/processed/horse_history.csv')
    p.add_argument('--month', default='2026-07')
    p.add_argument('--output-dir', default='backtest_results')
    p.add_argument('--min-runners', type=int, default=1)
    p.add_argument('--max-races', type=int, default=0)
    a = p.parse_args()

    df = pd.read_csv(a.input, encoding='utf-8-sig', low_memory=False)
    needed = {'race_date', '競馬場', 'レース番号', 'horse_key', '着順'}
    missing_cols = needed - set(df.columns)
    if missing_cols:
        raise ValueError(f'Missing columns: {sorted(missing_cols)}')
    dates = pd.to_datetime(df['race_date'], errors='coerce')
    month = pd.Period(a.month, freq='M')
    subset = df.loc[(dates.dt.to_period('M') == month) & df['競馬場'].isin(TRACKS)].copy()
    subset['date_key'] = pd.to_datetime(subset['race_date']).dt.strftime('%Y-%m-%d')
    subset['race_num'] = pd.to_numeric(subset['レース番号'], errors='coerce')
    groups = subset.groupby(['date_key', '競馬場', 'race_num'], dropna=True)
    keys = sorted((date, track, int(race)) for (date, track, race), g in groups if race >= 1)
    if a.max_races > 0:
        keys = keys[:a.max_races]

    output = Path(a.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows, summaries, failures, misses = [], [], [], []

    for i, (date, track, race) in enumerate(keys, 1):
        try:
            rated = rating(df, date, track, race).reset_index(drop=True)
            n = len(rated)
            if n < a.min_runners:
                failures.append({'日付': date, '競馬場': track, 'R': race,
                                 '理由': '出走頭数不足', '詳細': f'{n}頭 / 最低{a.min_runners}頭'})
                continue
            finish, missing, invalid, out_of_range = classify_finish(rated['実際の着順(検証用)'], n)
            # Never guess whether a nonnumeric result is a scratch, DNF, or other status.
            if missing.any() or invalid.any() or out_of_range.any():
                reasons = []
                if missing.any(): reasons.append('着順欠損')
                if invalid.any(): reasons.append('着順が数値以外（取消・中止等の可能性）')
                if out_of_range.any(): reasons.append('着順が範囲外・不正値')
                examples = rated.loc[missing | invalid | out_of_range,
                                     ['馬名', '実際の着順(検証用)']].head(5).to_dict('records')
                failures.append({'日付': date, '競馬場': track, 'R': race,
                                 '理由': ' / '.join(reasons), '詳細': str(examples)})
                continue
            # A missing winner or duplicate finish labels can corrupt evaluation.
            if int((finish == 1).sum()) != 1:
                failures.append({'日付': date, '競馬場': track, 'R': race,
                                 '理由': '勝ち馬が不明・重複', '詳細': f'1着の記録数={int((finish == 1).sum())}'})
                continue
            rated['AI順位'] = range(1, n + 1)
            rated.insert(0, '日付', date)
            rated.insert(1, '競馬場', track)
            rated.insert(2, 'R', race)
            rated['3着以内'] = finish.le(3)
            rows.append(rated)
            top = rated.iloc[0]
            top3 = rated.head(3)
            top4 = rated.head(4)
            winner = rated.loc[finish.eq(1)].iloc[0]
            winner_rank = int(winner['AI順位'])
            top_finish = int(finish.iloc[0])
            summaries.append({'日付': date, '競馬場': track, 'R': race, '頭数': n,
                              '評価1位勝利': int(top_finish == 1),
                              '評価1位3着以内': int(top_finish <= 3),
                              '評価上位3頭の3着内頭数': int(top3['3着以内'].sum()),
                              '評価上位4頭の3着内頭数': int(top4['3着以内'].sum()),
                              '勝ち馬AI順位': winner_rank,
                              '評価1位の確かさ(%)': top['確かさ(%)']})
            if top_finish >= 4:
                misses.append({'日付': date, '競馬場': track, 'R': race, '頭数': n,
                               '失敗分類': '評価1位が4着以下', '馬名': top['馬名'],
                               'AI順位': 1, '実際の着順': top_finish,
                               '評価点': top['評価点'], '確かさ(%)': top['確かさ(%)'],
                               '過去走数': top['過去走数']})
            if winner_rank >= 5:
                misses.append({'日付': date, '競馬場': track, 'R': race, '頭数': n,
                               '失敗分類': '勝ち馬のAI順位が5位以下', '馬名': winner['馬名'],
                               'AI順位': winner_rank, '実際の着順': 1,
                               '評価点': winner['評価点'], '確かさ(%)': winner['確かさ(%)'],
                               '過去走数': winner['過去走数']})
        except Exception as exc:
            failures.append({'日付': date, '競馬場': track, 'R': race,
                             '理由': '処理エラー', '詳細': str(exc)[:500]})
        if i % 25 == 0:
            print(f'Processed {i}/{len(keys)}', flush=True)

    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    races = pd.DataFrame(summaries)
    detail.to_csv(output / 'horse_ratings.csv', index=False, encoding='utf-8-sig')
    races.to_csv(output / 'race_summary.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(failures, columns=['日付', '競馬場', 'R', '理由', '詳細']).to_csv(
        output / 'excluded_races.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(misses, columns=['日付', '競馬場', 'R', '頭数', '失敗分類', '馬名',
                                  'AI順位', '実際の着順', '評価点', '確かさ(%)', '過去走数']).to_csv(
        output / 'prediction_misses.csv', index=False, encoding='utf-8-sig')

    aggregate = []
    for track in ['全場'] + sorted(TRACKS):
        part = races if track == '全場' else (races[races['競馬場'] == track] if not races.empty else races)
        n = len(part)
        aggregate.append({'競馬場': track, '検証レース数': n,
                          '評価1位勝率(%)': round(100 * part['評価1位勝利'].mean(), 2) if n else None,
                          '評価1位複勝率(%)': round(100 * part['評価1位3着以内'].mean(), 2) if n else None,
                          '上位3頭の3着内捕捉率(%)': round(100 * part['評価上位3頭の3着内頭数'].sum() / (3*n), 2) if n else None,
                          '上位4頭の3着内捕捉率(%)': round(100 * part['評価上位4頭の3着内頭数'].sum() / (3*n), 2) if n else None})
    pd.DataFrame(aggregate).to_csv(output / 'overall_summary.csv', index=False, encoding='utf-8-sig')
    print('Completed:', len(races), 'Excluded:', len(failures), 'Miss records:', len(misses), 'Output:', output)


if __name__ == '__main__':
    main()
