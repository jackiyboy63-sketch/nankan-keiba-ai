import streamlit as st
import pandas as pd
from nar_import import read_zip, VENUES

st.set_page_config(page_title='南関東競馬AI v0.3', layout='wide')
st.title('🏇 南関東競馬AI v0.3')
st.caption('NAR公式ZIP・CSV読み込み診断版｜自動取得・機械学習・自動投票は未実装')
st.warning('データ確認用です。予測精度・期待値は未検証のため、推奨購入額は0円です。')
st.info('NAR公式のレース情報ZIPを、解凍せずに選んでください。')
files = st.file_uploader('NAR公式レース情報ZIP・オッズZIP（複数選択可）', type=['zip'], accept_multiple_files=True)
if not files:
    st.write('ZIPが未選択です。選択後、ここにファイル名と読み込み件数が表示されます。')
    st.stop()

all_tables = {}
for file in files:
    st.write(f'📦 選択ファイル：**{file.name}**（{file.size / 1024 / 1024:.2f} MB）')
    try:
        with st.spinner(f'{file.name} を読み込み中…'):
            tables, messages = read_zip(file.getvalue())
        for message in messages:
            st.write('・' + message)
        for kind, df in tables.items():
            all_tables.setdefault(kind, []).append(df)
    except Exception as exc:
        st.error(f'{file.name} の処理に失敗：{type(exc).__name__}: {exc}')

frames = {k: pd.concat(v, ignore_index=True).drop_duplicates() for k, v in all_tables.items()}
if not frames:
    st.error('読み込み可能な南関東データがありません。上の診断結果を確認してください。')
    st.stop()
st.success('読み込み完了！')
for kind, label in [('racelist','レース一覧'), ('horselist','出馬表'), ('payback','払戻'), ('odds','オッズ')]:
    if kind in frames:
        st.metric(f'{label}（南関東）', f'{len(frames[kind]):,} 件')

base = frames.get('racelist', frames.get('horselist'))
venues = sorted(base['競馬場'].dropna().unique().tolist())
venue = st.selectbox('競馬場', venues)
dates = sorted(base.loc[base['競馬場'].eq(venue), '日付'].dropna().unique(), reverse=True)
date = st.selectbox('開催日', dates, format_func=lambda x: pd.Timestamp(x).strftime('%Y-%m-%d'))
sel = base.loc[base['競馬場'].eq(venue) & base['日付'].eq(date)]
races = sorted(sel['R'].dropna().astype(int).unique().tolist())
race = st.selectbox('レース', races, format_func=lambda x: f'{x}R')

for kind, label in [('racelist','レース情報'), ('horselist','出馬表'), ('payback','払戻'), ('odds','オッズ')]:
    if kind not in frames:
        continue
    df = frames[kind]
    part = df.loc[df['競馬場'].eq(venue) & df['日付'].eq(date) & df['R'].eq(race)]
    st.subheader(label)
    if part.empty:
        st.caption('該当データはありません。')
    else:
        st.dataframe(part.drop(columns=['日付','R'], errors='ignore'), use_container_width=True, hide_index=True)
        st.download_button(f'{label}をCSVで保存', data=part.to_csv(index=False).encode('utf-8-sig'), file_name=f'{kind}_{venue}_{pd.Timestamp(date).strftime("%Y%m%d")}_{race}R.csv', mime='text/csv', key=f'dl_{kind}')
st.caption('公式データの利用・再配布には提供元の利用条件を確認してください。')
