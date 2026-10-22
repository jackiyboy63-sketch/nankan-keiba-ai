"""Shared history preparation and conservative validation for retrospective tests."""
from dataclasses import dataclass
import numpy as np
import pandas as pd

REQUIRED = {'race_date','着順','距離','頭数','上がり3F','タイム','競馬場','レース番号',
            'horse_key','race_key','父馬名','母父馬名','馬番','馬名','馬場'}

@dataclass(frozen=True)
class PreparedHistory:
    frame: pd.DataFrame


def parse_seconds(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if s.endswith('.0'):
        s = s[:-2]
    if not s.isdigit():
        return np.nan
    v = int(s)
    minutes, remainder = divmod(v, 1000)
    # Packed M:SS.d; zero and impossible seconds are missing, never fast times.
    return minutes * 60 + remainder / 10 if v > 0 and remainder < 600 else np.nan


def prepare(df):
    if isinstance(df, PreparedHistory):
        return df.frame
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError('不足列: ' + ', '.join(sorted(missing)))
    d = df[sorted(REQUIRED)].copy()
    d['race_date'] = pd.to_datetime(d['race_date'], errors='raise')
    if d['race_date'].isna().any():
        raise ValueError('日付欠損')
    if d['horse_key'].isna().any() or d['horse_key'].astype(str).str.strip().eq('').any():
        raise ValueError('馬識別子欠損')
    if d['race_key'].isna().any():
        raise ValueError('レース識別子欠損')
    # Conflicting/duplicate runners must not silently enter race baselines or features.
    if d.duplicated(['race_key','馬番']).any() or d.duplicated(['race_key','horse_key']).any():
        raise ValueError('レース内の馬番または馬識別子が重複')
    for col, new in [('着順','着順_num'),('距離','距離_num'),('頭数','頭数_num'),('上がり3F','上がり_num')]:
        d[new] = pd.to_numeric(d[col], errors='coerce')
    d['seconds'] = d['タイム'].map(parse_seconds)
    return d


def validate_entries(entries):
    if entries.empty:
        raise ValueError('対象レースなし（過去結果専用。ライブ出走表は別途必要）')
    for col in ['距離_num','頭数_num']:
        values = entries[col]
        if values.isna().any() or values.nunique() != 1 or (values <= 0).any():
            raise ValueError('対象レースの条件が欠損・不一致: ' + col)
    if entries['頭数_num'].iloc[0] != len(entries):
        raise ValueError('頭数と収録馬数が不一致')
    nums = pd.to_numeric(entries['馬番'], errors='coerce')
    if nums.isna().any() or (nums <= 0).any() or (nums % 1 != 0).any() or nums.duplicated().any():
        raise ValueError('馬番が欠損・不正・重複')


def validate_results(entries):
    validate_entries(entries)
    f = entries['着順_num']
    # DNF/scratches/dead heats need explicit status rules. Quarantine, do not guess.
    if f.isna().any() or sorted(f.tolist()) != list(range(1, len(entries) + 1)):
        raise ValueError('完全な着順集合ではない（取消・中止・同着等を含む可能性）')
