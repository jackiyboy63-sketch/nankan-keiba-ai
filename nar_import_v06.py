import io
import re
import zipfile
import pandas as pd

VENUES = ('大井', '船橋', '川崎', '浦和')
KEYS = ['競馬場', '競走年月日', 'レース番号']

def read_csv_bytes(blob):
    last = None
    for enc in ('utf-8-sig', 'cp932'):
        try:
            return pd.read_csv(io.BytesIO(blob), encoding=enc, low_memory=False)
        except (UnicodeDecodeError, UnicodeError) as e:
            last = e
    raise ValueError(f'CSV文字コードを読み取れません: {last}')

def read_uploads(uploaded_files):
    pieces = {'racelist': [], 'horselist': [], 'payback': []}
    notes = []
    for file in uploaded_files:
        try:
            blob = file.getvalue()
            if file.name.lower().endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    entries = [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.csv') and i.file_size <= 80_000_000]
            else:
                entries = [(file.name, blob)]
            for name, raw in entries:
                base = name.replace('\\', '/').split('/')[-1].lower()
                kind = next((k for k in pieces if k in base), None)
                if kind is None:
                    notes.append(f'{name}: 対象外のCSV')
                    continue
                df = read_csv_bytes(raw)
                if not set(KEYS).issubset(df.columns):
                    notes.append(f'{name}: 必須列不足')
                    continue
                df['競馬場'] = df['競馬場'].astype(str).str.strip()
                df = df[df['競馬場'].isin(VENUES)].copy()
                df['日付'] = pd.to_datetime(df['競走年月日'].astype(str), format='%Y%m%d', errors='coerce')
                df['R'] = pd.to_numeric(df['レース番号'], errors='coerce')
                df = df.dropna(subset=['日付', 'R'])
                if kind == 'horselist':
                    for col in ('馬番', '着順', 'タイム', '上がり3F', '人気'):
                        if col in df:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    if '馬名' not in df:
                        notes.append(f'{name}: 馬名列なし')
                        continue
                    df['馬名'] = df['馬名'].astype(str).str.strip()
                pieces[kind].append(df)
        except Exception as e:
            notes.append(f'{file.name}: 読み込み失敗 ({e})')
    out = {}
    for kind, frames in pieces.items():
        if frames:
            df = pd.concat(frames, ignore_index=True)
            uniq = ['競馬場', '日付', 'R'] + (['馬番'] if kind == 'horselist' else [])
            out[kind] = df.drop_duplicates(subset=uniq, keep='last').reset_index(drop=True)
    return out, notes

def historical_scores(target, history, race_meta, asof):
    """No odds/popularity. Uses only finished runs strictly before asof."""
    rows = []
    history = history[(history['日付'] < asof) & (history['日付'] >= asof - pd.Timedelta(days=730)) & history['着順'].notna()].copy()
    history = history.merge(race_meta[['競馬場','日付','R','距離','馬場']].drop_duplicates(['競馬場','日付','R']), on=['競馬場','日付','R'], how='left', suffixes=('','_race'))
    for _, horse in target.iterrows():
        past = history[history['馬名'] == horse['馬名']].sort_values('日付', ascending=False)
        recent = past.head(5)
        same = past[(past['競馬場'] == horse['競馬場']) & (past['距離'] == horse.get('距離'))]
        n = len(recent)
        # 30 course suitability, 20 early speed (unavailable), 20 recent form,
        # 10 time, 15 closing kick, 5 pace (unavailable).
        # Scores with no valid observations remain NA, not zero.
        suitability = round(30 * (same['着順'].le(3).mean()), 1) if len(same) else None
        form = round(20 * recent['着順'].le(3).mean(), 1) if n else None
        closing = round(15 * recent['上がり3F'].notna().mean() * (recent['着順'].le(3).mean()), 1) if n and recent['上がり3F'].notna().any() else None
        comparable = same[pd.to_numeric(same['タイム'], errors='coerce').gt(0)]
        best_time = comparable['タイム'].min() if len(comparable) else None
        rows.append({'馬番':horse['馬番'], '馬名':horse['馬名'], '過去走数':len(past), '直近5走3着内率':round(recent['着順'].le(3).mean()*100,1) if n else None, '同場同距離走数':len(same), '同場同距離3着内率':round(same['着順'].le(3).mean()*100,1) if len(same) else None, '同場同距離最速タイム(原データ)':best_time, '適性(30)':suitability, '近走(20)':form, '末脚暫定(15)':closing, '先行力(20)':'未評価', '時計(10)':'未評価', '展開(5)':'未評価', '評価済点合計(最大65)':round(sum(x for x in (suitability,form,closing) if x is not None),1), '評価済配点':sum(w for x,w in ((suitability,30),(form,20),(closing,15)) if x is not None)})
    return pd.DataFrame(rows).sort_values(['評価済配点','評価済点合計(最大65)'],ascending=False)
