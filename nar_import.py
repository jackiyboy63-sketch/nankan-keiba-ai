"""NAR monthly race ZIP reader; preserves original Japanese CSV headers."""
import io
import zipfile
from pathlib import PurePosixPath
import pandas as pd

VENUES = ('大井', '船橋', '川崎', '浦和')
KINDS = ('racelist', 'horselist', 'payback', 'odds')
REQUIRED = {
    'racelist': {'競馬場', '競走年月日', 'レース番号', 'レース名'},
    'horselist': {'競馬場', '競走年月日', 'レース番号', '馬番', '馬名'},
    'payback': {'競馬場', '競走年月日', 'レース番号'},
    'odds': {'競馬場', '競走年月日', 'レース番号'},
}

def read_zip(blob):
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        raise ValueError('ZIP形式ではないか、ZIPが破損しています。')
    tables = {}
    diagnostics = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.file_size > 80_000_000:
                diagnostics.append(f'{info.filename}: ファイルが大きすぎるためスキップ')
                continue
            name = PurePosixPath(info.filename).name.lower()
            if not name.endswith('.csv'):
                continue
            kind = next((k for k in KINDS if k in name), None)
            if kind is None:
                diagnostics.append(f'{info.filename}: 対象外のCSV')
                continue
            try:
                df = pd.read_csv(io.BytesIO(archive.read(info)), encoding='utf-8-sig', low_memory=False)
                df.columns = df.columns.astype(str).str.strip().str.lstrip('\ufeff')
                missing = REQUIRED[kind] - set(df.columns)
                if missing:
                    diagnostics.append(f'{info.filename}: 必須列が不足 {", ".join(sorted(missing))}')
                    continue
                df['競馬場'] = df['競馬場'].astype('string').str.strip()
                df = df[df['競馬場'].isin(VENUES)].copy()
                df['日付'] = pd.to_datetime(df['競走年月日'].astype('string'), format='%Y%m%d', errors='coerce')
                df['R'] = pd.to_numeric(df['レース番号'], errors='coerce').astype('Int64')
                df = df.dropna(subset=['日付', 'R'])
                tables.setdefault(kind, []).append(df)
                diagnostics.append(f'{info.filename}: 南関東 {len(df):,} 件を読み込み')
            except Exception as exc:
                diagnostics.append(f'{info.filename}: 読み込みエラー {type(exc).__name__}: {exc}')
    result = {kind: pd.concat(parts, ignore_index=True).drop_duplicates() for kind, parts in tables.items()}
    return result, diagnostics
