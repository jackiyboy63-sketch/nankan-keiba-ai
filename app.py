import io
import zipfile
import pandas as pd
import streamlit as st
from nar_import import read_zip, VENUES, KINDS, REQUIRED

st.set_page_config(page_title='南関東競馬AI v0.4', layout='wide')
st.title('🏇 南関東競馬AI v0.4')
st.caption('スマホ向けアップロード診断版｜予測・自動取得・自動投票は未実装')
st.warning('データ確認専用です。予想の精度・期待値は未検証のため、推奨購入額は0円です。')
st.info('まず下の「テストCSVを保存」を押し、保存した小さなCSVをアップロードしてみてください。')

sample = '競馬場,競走年月日,レース番号,馬番,馬名\n大井,20261020,1,1,テスト馬\n'.encode('utf-8-sig')
st.download_button('① テストCSVを保存（約0.1KB）', sample, 'upload_test.csv', mime='text/csv')
st.write('② ZIPまたはCSVを1つ選択してください。')
file = st.file_uploader('ファイルを選ぶ（ZIP / CSV）', type=['zip', 'csv'], accept_multiple_files=False, key='diagnostic_upload_v04')
if file is None:
    st.info('現在：ファイル未受信。選択後もこの表示のままなら、CSVの解析前にアップロードが止まっています。')
    st.caption('その場合は、表示されている画面とブラウザ名を教えてください。')
    st.stop()

st.success('ファイルを受信しました！')
st.write(f'受信ファイル：{file.name}')
st.write(f'受信サイズ：{file.size:,} バイト')
blob = file.getvalue()
st.write(f'実際に受信したデータ：{len(blob):,} バイト')
if not blob:
    st.error('空ファイルです。')
    st.stop()

frames = {}
try:
    if file.name.lower().endswith('.zip'):
        st.write('ZIP形式として解析します。')
        frames, messages = read_zip(blob)
        for message in messages:
            st.write('・' + message)
    elif file.name.lower().endswith('.csv'):
        st.write('CSV形式として解析します。')
        df = pd.read_csv(io.BytesIO(blob), encoding='utf-8-sig', low_memory=False)
        df.columns = df.columns.astype(str).str.strip().str.lstrip('\ufeff')
        st.write('CSVの列名：', list(df.columns[:20]))
        kind = next((k for k in KINDS if k in file.name.lower()), None)
        if kind is None:
            kind = next((k for k in KINDS if REQUIRED[k].issubset(df.columns)), None)
        if kind is None:
            st.warning('ファイルの受信とCSV解析は成功しましたが、NAR形式ではないため一覧表示はしません。テストCSVの場合はこれで正常です。')
        else:
            missing = REQUIRED[kind] - set(df.columns)
            if missing:
                st.warning('必須列が不足しています：' + ', '.join(sorted(missing)))
            else:
                df['競馬場'] = df['競馬場'].astype('string').str.strip()
                df = df[df['競馬場'].isin(VENUES)].copy()
                df['日付'] = pd.to_datetime(df['競走年月日'].astype('string'), format='%Y%m%d', errors='coerce')
                df['R'] = pd.to_numeric(df['レース番号'], errors='coerce').astype('Int64')
                df = df.dropna(subset=['日付', 'R'])
                frames[kind] = df
    else:
        st.error('ZIPまたはCSVを選んでください。')
except Exception as exc:
    st.error(f'解析エラー：{type(exc).__name__}: {exc}')
    st.stop()

if not frames:
    st.info('アップロード診断はここまでです。データ一覧の表示対象はありません。')
    st.stop()

st.success('NARデータの解析に成功しました。')
for kind, label in [('racelist','レース一覧'), ('horselist','出馬表'), ('payback','払戻'), ('odds','オッズ')]:
    if kind in frames:
        st.metric(label + '（南関東）', f'{len(frames[kind]):,} 件')

base = frames.get('racelist')
if base is None:
    base = frames.get('horselist')
if base is None:
    base = next(iter(frames.values()))
if base.empty:
    st.warning('南関東4場の該当データはありません。')
    st.stop()
venue = st.selectbox('競馬場', sorted(base['競馬場'].dropna().unique().tolist()))
dates = sorted(base.loc[base['競馬場'].eq(venue), '日付'].dropna().unique(), reverse=True)
if not dates:
    st.stop()
date = st.selectbox('開催日', dates, format_func=lambda x: pd.Timestamp(x).strftime('%Y-%m-%d'))
sel = base.loc[base['競馬場'].eq(venue) & base['日付'].eq(date)]
races = sorted(sel['R'].dropna().astype(int).unique().tolist())
if not races:
    st.stop()
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
        st.download_button(f'{label}をCSVで保存', part.to_csv(index=False).encode('utf-8-sig'), file_name=f'{kind}_{venue}_{pd.Timestamp(date).strftime("%Y%m%d")}_{race}R.csv', mime='text/csv', key=f'dl_{kind}')
st.caption('NAR公式データの利用・再配布には提供元の利用条件を確認してください。')
