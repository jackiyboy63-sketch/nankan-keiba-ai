"""Build Nankan horse history from official monthly NAR ZIPs.
Usage: python nar_history.py --input data --output data/processed
"""
import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

VENUES = {'大井', '船橋', '川崎', '浦和'}
KEY = ['競馬場', '競走年月日', 'レース番号']
IDENTITY = ['馬名', '生年月日', '父馬名', '母馬名']


def load_csv(raw):
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding, dtype=str, low_memory=False)
        except UnicodeDecodeError:
            pass
    raise ValueError('Unsupported CSV encoding')


def normalize(s):
    return s.fillna('').astype(str).str.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data')
    parser.add_argument('--output', default='data/processed')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    horse_frames, race_frames = [], []
    archives = sorted(Path(args.input).rglob('*.zip'))
    if not archives:
        raise SystemExit('No ZIP archives found')
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as z:
                for member in z.namelist():
                    name = Path(member).name.lower()
                    if not name.endswith('.csv'):
                        continue
                    if 'horselist' in name:
                        kind = 'horse'
                    elif 'racelist' in name:
                        kind = 'race'
                    else:
                        continue
                    frame = load_csv(z.read(member))
                    required = KEY + (IDENTITY + ['馬番', '着順'] if kind == 'horse' else ['距離', '馬場'])
                    if any(c not in frame.columns for c in required):
                        raise ValueError(f'Missing required columns: {archive.name}/{member}')
                    frame = frame[frame['競馬場'].isin(VENUES)].copy()
                    frame['_source'] = archive.name + '/' + member
                    (horse_frames if kind == 'horse' else race_frames).append(frame)
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise RuntimeError(f'Cannot process {archive}: {exc}') from exc
    if not horse_frames or not race_frames:
        raise SystemExit('No Nankan horse/race CSV data found')
    horses = pd.concat(horse_frames, ignore_index=True)
    races = pd.concat(race_frames, ignore_index=True)
    for col in KEY:
        horses[col] = normalize(horses[col])
        races[col] = normalize(races[col])
    for col in IDENTITY + ['馬番']:
        horses[col] = normalize(horses[col])
    # Require complete identity: never silently merge ambiguous horses.
    valid = horses[IDENTITY].ne('').all(axis=1)
    excluded = horses.loc[~valid].copy()
    horses = horses.loc[valid].copy()
    horses['horse_key'] = horses[IDENTITY].agg('|'.join, axis=1)
    horses['race_key'] = horses[KEY].agg('|'.join, axis=1)
    races['race_key'] = races[KEY].agg('|'.join, axis=1)
    # Duplicate records from overlapping archives are allowed only if identical
    # in the essential result fields; conflicting rows are quarantined.
    result_cols = [c for c in ['着順', 'タイム', '上がり3F', '着差'] if c in horses.columns]
    for col in result_cols:
        horses[col] = normalize(horses[col])
    duplicate_key = ['race_key', '馬番']
    conflict = horses.groupby(duplicate_key, dropna=False)[['horse_key'] + result_cols].nunique(dropna=False).gt(1).any(axis=1)
    conflicting_keys = conflict[conflict].index
    bad = pd.MultiIndex.from_frame(horses[duplicate_key]).isin(conflicting_keys)
    conflicts = horses.loc[bad].copy()
    horses = horses.loc[~bad].drop_duplicates(subset=duplicate_key, keep='first')
    race_conflict = races.groupby('race_key')[['距離', '馬場']].nunique(dropna=False).gt(1).any(axis=1)
    conflicting_races = set(race_conflict[race_conflict].index)
    races = races.loc[~races['race_key'].isin(conflicting_races)].drop_duplicates('race_key')
    # Validate date; historical records must be sorted strictly by race date.
    horses['race_date'] = pd.to_datetime(horses['競走年月日'], format='%Y%m%d', errors='coerce')
    bad_date = horses['race_date'].isna()
    excluded = pd.concat([excluded, horses.loc[bad_date]], ignore_index=True)
    horses = horses.loc[~bad_date]
    race_info = races[['race_key', '距離', '馬場'] + [c for c in ['天候', '回り', '芝ダート区分', '頭数'] if c in races.columns]]
    history = horses.merge(race_info, on='race_key', how='left', validate='many_to_one', suffixes=('', '_race'))
    history = history.sort_values(['horse_key', 'race_date', 'レース番号', 'race_key'])
    history['prior_starts'] = history.groupby('horse_key').cumcount()
    # This is an archival history, NOT a pre-race feature table: race-day
    # results must be shifted/filtered to dates strictly before prediction date.
    history.to_csv(out / 'horse_history.csv', index=False, encoding='utf-8-sig')
    conflicts.to_csv(out / 'conflicting_horse_rows.csv', index=False, encoding='utf-8-sig')
    excluded.to_csv(out / 'excluded_identity_or_date.csv', index=False, encoding='utf-8-sig')
    print(f'Archives: {len(archives)}; history rows: {len(history)}; horses: {history.horse_key.nunique()}')
    print(f'Conflicting horse rows: {len(conflicts)}; excluded identity/date: {len(excluded)}; conflicting races: {len(conflicting_races)}')
    print(f'Output: {out / "horse_history.csv"}')


if __name__ == '__main__':
    main()
