"""Audit official NAR race ZIP/CSV fields without changing original data.
Run: python nar_audit.py --output nar_audit_report.md
"""
import argparse
import io
import zipfile
from collections import defaultdict
from pathlib import Path
import pandas as pd

VENUES = {'大井', '船橋', '川崎', '浦和'}
GROUPS = {
    '識別・血統': ['馬名', '馬ID', '血統登録番号', '父馬名', '母馬名', '母父馬名', '母の父馬名', '父', '母父'],
    '成績・時計': ['着順', 'タイム', '着差', '上がり3F', '上がり4F', '走破タイム'],
    '位置取り': ['通過順位', '通過順', '1コーナー', '2コーナー', '3コーナー', '4コーナー', 'コーナー通過順'],
    '条件・属性': ['競馬場', '競走年月日', 'レース番号', '距離', '馬場', '天候', '頭数', '枠番', '馬番', '騎手名', '調教師名', '斤量', '性齢'],
    '展開・ラップ': ['ハロンタイム1', 'ハロンタイム2', 'ハロンタイム3', 'ハロンタイム4', '上がり3F'],
}

def kind_for(name):
    low = name.lower()
    return next((k for k in ('horselist', 'racelist', 'payback') if k in low), None)

def read_csv(raw):
    for enc in ('utf-8-sig', 'cp932'):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, low_memory=False)
        except UnicodeError:
            continue
    raise ValueError('CSV encoding unsupported')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='nar_audit_report.md')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    paths = sorted(set(root.glob('*.zip')) | set(root.glob('*.csv')) | set((root/'data').glob('*.zip')) | set((root/'data').glob('*.csv')))
    stats = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    rows = defaultdict(int)
    sources = defaultdict(int)
    errors = []
    for path in paths:
        try:
            if path.suffix.lower() == '.zip':
                with zipfile.ZipFile(path) as z:
                    entries = [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.csv')]
            else:
                entries = [(path.name, path.read_bytes())]
            for name, raw in entries:
                kind = kind_for(name)
                if not kind:
                    continue
                try:
                    df = read_csv(raw)
                    if '競馬場' in df.columns:
                        df = df[df['競馬場'].astype(str).str.strip().isin(VENUES)]
                    rows[kind] += len(df)
                    sources[kind] += 1
                    for col in df.columns:
                        nonempty = df[col].notna() & df[col].astype(str).str.strip().ne('')
                        stats[kind][str(col)][0] += int(nonempty.sum())
                        stats[kind][str(col)][1] += len(df)
                except Exception as e:
                    errors.append(f'{path.name}/{name}: {type(e).__name__}: {e}')
        except Exception as e:
            errors.append(f'{path.name}: {type(e).__name__}: {e}')
    lines = ['# NAR公式データ項目診断', '', '## 読み取り概要', '', '| 種類 | CSV数 | 行数（重複除去前） |', '|---|---:|---:|']
    for kind in ('horselist','racelist','payback'):
        lines.append(f'| {kind} | {sources[kind]} | {rows[kind]:,} |')
    lines += ['', '## 全列の充足率（南関4場）', '', '※同一データが複数ファイルにある場合、行数は重複します。充足率はCSV中に列が存在しない場合も欠測として集計しています。', '']
    for kind in ('horselist','racelist','payback'):
        lines += [f'### {kind}', '', '| 列名 | 非空件数 | 全行に対する充足率 |', '|---|---:|---:|']
        for col, (filled, present_total) in sorted(stats[kind].items()):
            total = rows[kind]
            lines.append(f'| {col.replace("|", "/")} | {filled:,} | {100*filled/total:.1f}% |' if total else f'| {col} | 0 | - |')
        lines.append('')
    lines += ['## 評価候補の列名確認', '']
    allcols = {col for kind in stats for col in stats[kind]}
    for group, candidates in GROUPS.items():
        found = [c for c in candidates if c in allcols]
        lines.append(f'- **{group}**: ' + (', '.join(found) if found else '候補名で一致なし（全列一覧を要確認）'))
    lines += ['', '## 読み込みエラー', '']
    lines.extend('- ' + e for e in errors) if errors else lines.append('なし')
    out = root / args.output
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Wrote {out} ({len(paths)} input files)')
    print(f'CSV: {dict(sources)} / rows: {dict(rows)} / errors: {len(errors)}')

if __name__ == '__main__':
    main()
