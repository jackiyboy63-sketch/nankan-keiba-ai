import io
import re
import pandas as pd
import streamlit as st
from nar_import import read_zip, VENUES, KINDS, REQUIRED

st.set_page_config(page_title='南関東競馬AI v0.5', layout='wide')
st.title('🏇 南関東競馬AI v0.5')
st.caption('NAR公式CSV対応｜全頭の根拠確認・評価準備版')
st.warning('予測モデルと回収率は未検証です。評価の欠測項目は採点せず、購入推奨額は0円です。')
st.info('スマホでは通常のChromeで開き、解凍済みのCSVを選んでください。ZIPが受信されない場合はCSVで進められます。')

files = st.file_uploader('NAR公式CSV（複数選択可）またはZIP', type=['csv', 'zip'], accept_multiple_files=True, key='upload_v05')
if not files:
    st.info('ファイル未選択です。まず202610_horselist.csvを選んでください。レース情報CSVも追加できます。')
    st.stop()

frames = {}
for file in files:
    st.write(f'受信：{file.name}（{file.size:,} バイト）')
    try:
        if file.name.lower().endswith('.zip'):
            parsed, messages = read_zip(file.getvalue())
            for msg in messages:
                st.caption(msg)
        else:
            df = pd.read_csv(io.BytesIO(file.getvalue()), encoding='utf-8-sig', low_memory=False)
            df.columns = df.columns.astype(str).str.strip().str.lstrip('\ufeff')
            kind = next((k for k in KINDS if k in file.name.lower()), None)
            if kind is None:
                kind = next((k for k in KINDS if REQUIRED[k].issubset(df.columns)), None)
            if kind is None or not REQUIRED[kind].issubset(df.columns):
                st.warning(f'{file.name}: 対応するNAR公式CSVの列が見つかりません。')
                continue
            df['競馬場'] = df['競馬場'].astype('string').str.strip()
            df = df[df['競馬場'].isin(VENUES)].copy()
            df['日付'] = pd.to_datetime(df['競走年月日'].astype('string'), format='%Y%m%d', errors='coerce')
            df['R'] = pd.to_numeric(df['レース番号'], errors='coerce').astype('Int64')
            df = df.dropna(subset=['日付', 'R'])
            parsed = {kind: df}
        for kind, df in parsed.items():
            frames.setdefault(kind, []).append(df)
    except Exception as exc:
        st.error(f'{file.name} の処理に失敗：{type(exc).__name__}: {exc}')
frames = {k: pd.concat(v, ignore_index=True).drop_duplicates() for k, v in frames.items()}
if not frames:
    st.stop()
for kind, label in [('racelist','レース情報'),('horselist','出馬表'),('payback','払戻'),('odds','オッズ')]:
    if kind in frames:
        st.metric(label + '（南関東）', f'{len(frames[kind]):,} 件')

base = frames.get('horselist')
if base is None:
    base = frames.get('racelist')
if base is None or base.empty:
    st.warning('出馬表またはレース情報CSVを追加してください。')
    st.stop()
venue = st.selectbox('競馬場', sorted(base['競馬場'].dropna().unique()))
dates = sorted(base.loc[base['競馬場'].eq(venue), '日付'].dropna().unique(), reverse=True)
if not dates:
    st.stop()
date = st.selectbox('開催日', dates, format_func=lambda d: pd.Timestamp(d).strftime('%Y-%m-%d'))
rows = base[base['競馬場'].eq(venue) & base['日付'].eq(date)]
races = sorted(rows['R'].dropna().astype(int).unique())
if not races:
    st.stop()
race = st.selectbox('レース', races, format_func=lambda n: f'{n}R')

if 'racelist' in frames:
    r = frames['racelist']
    info = r[r['競馬場'].eq(venue) & r['日付'].eq(date) & r['R'].eq(race)]
    if not info.empty:
        st.subheader('レース情報')
        show = [c for c in ['レース名','距離','馬場状態','競走種別名称','発走時刻','頭数'] if c in info.columns]
        if show:
            st.dataframe(info[show], hide_index=True, use_container_width=True)

st.subheader('全頭評価（取得できた根拠のみ）')
st.caption('正式配点：適性30／先行力20／近走内容20／時計10／末脚15／展開5＝100点。欠測項目は0点扱いせず「未評価」にします。')
if 'horselist' not in frames:
    st.warning('出馬表CSVが必要です。202610_horselist.csvをアップロードしてください。')
    st.stop()
h = frames['horselist']
sub = h[h['競馬場'].eq(venue) & h['日付'].eq(date) & h['R'].eq(race)].copy()
if sub.empty:
    st.warning('選択したレースの出馬表がありません。')
    st.stop()

# The NAR monthly horselist contains aggregate lifetime records, not complete
# pre-race running positions or verified time series. Avoid score fabrication.
def record_info(value):
    if pd.isna(value):
        return None
    m = re.fullmatch(r'\s*(\d+)\s*[-－]\s*(\d+)\s*[-－]\s*(\d+)\s*[-－]\s*(\d+)\s*', str(value))
    if not m:
        return None
    win, second, third, other = map(int, m.groups())
    total = win + second + third + other
    return (total, win, second, third, (win + second + third) / total if total else None)

result = []
for _, row in sub.sort_values('馬番', key=lambda x: pd.to_numeric(x, errors='coerce')).iterrows():
    course = record_info(row.get('当競馬場成績'))
    distance = record_info(row.get('うち当距離成績'))
    def desc(stats):
        if stats is None:
            return '不明'
        n, w, s, t, rate = stats
        return f'{n}走 {w}-{s}-{t}／3着内率{rate:.1%}' if rate is not None else '0走（実績なし）'
    evidence = [stats for stats in (course, distance) if stats is not None and stats[0] >= 10]
    certainty = '参考：集計実績あり' if evidence else '低：実績不足・欠測'
    result.append({
        '馬番': row.get('馬番'), '馬名': row.get('馬名'), '騎手': row.get('騎手名', ''),
        '当競馬場実績': desc(course), '当距離実績': desc(distance),
        '最高タイム（原文）': row.get('最高タイム', ''),
        '適性30点': '未評価', '先行20点': '未評価', '近走20点': '未評価',
        '時計10点': '未評価', '末脚15点': '未評価', '展開5点': '未評価',
        '合計100点': '算出不可', '根拠の確かさ': certainty,
    })
out = pd.DataFrame(result)
st.dataframe(out, hide_index=True, use_container_width=True)
st.download_button('全頭の根拠一覧をCSVで保存', out.to_csv(index=False).encode('utf-8-sig'), file_name=f'全頭根拠_{venue}_{pd.Timestamp(date).strftime("%Y%m%d")}_{race}R.csv', mime='text/csv')
st.info('「当競馬場成績」「うち当距離成績」は累積成績の参考値です。集計時点・馬場状態・相手関係を区別できないため、適性30点へ機械的に換算していません。最高タイムも条件の整合性が確認できるまでは採点しません。')
st.caption('重要：月間CSVには確定後の着順等が含まれることがあります。予想時点の情報と区別できない項目を予測根拠に使うと結果の先取りになるため、今回は使いません。')
st.caption('NAR公式データの利用・再配布には提供元の利用条件を確認してください。')
