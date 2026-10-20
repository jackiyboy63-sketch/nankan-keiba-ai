import streamlit as st
import pandas as pd
from nar_import import read_uploads, historical_scores

st.set_page_config(page_title='南関競馬AI v0.6', layout='wide')
st.title('南関競馬AI v0.6')
st.caption('過去成績の蓄積・照合。人気とオッズは能力評価に使用しません。')
files = st.file_uploader('公式ZIP・CSVを複数選択（9月ZIPと10月CSVなど）', type=['zip','csv'], accept_multiple_files=True)
if not files:
    st.info('9月ZIPと10月CSVをアップロードしてください。')
    st.stop()
tables, notes = read_uploads(files)
for note in notes:
    st.warning(note)
if 'horselist' not in tables:
    st.error('horselistが見つかりません。')
    st.stop()
horses = tables['horselist']
st.success(f'出走データ {len(horses):,}件 / 対象期間 {horses["日付"].min().date()} ～ {horses["日付"].max().date()}')
venue = st.selectbox('競馬場', sorted(horses['競馬場'].unique()))
dates = sorted(horses.loc[horses['競馬場']==venue,'日付'].dropna().unique(), reverse=True)
date = st.selectbox('開催日', dates, format_func=lambda x: pd.Timestamp(x).strftime('%Y-%m-%d'))
races = sorted(horses.loc[(horses['競馬場']==venue)&(horses['日付']==date),'R'].dropna().unique())
race = st.selectbox('レース', races, format_func=lambda x: f'{int(x)}R')
target = horses[(horses['競馬場']==venue)&(horses['日付']==date)&(horses['R']==race)].copy()
st.subheader('出走馬')
st.dataframe(target[[x for x in ['馬番','馬名','騎手名','着順'] if x in target]],hide_index=True,use_container_width=True)
if 'racelist' not in tables:
    st.warning('racelistがないため距離別比較はできません。対象月のracelistもアップロードしてください。')
    st.stop()
meta = tables['racelist']
if not {'距離','馬場'}.issubset(meta.columns):
    st.warning('racelistに距離または馬場列がありません。')
    st.stop()
target = target.merge(meta[['競馬場','日付','R','距離','馬場']].drop_duplicates(['競馬場','日付','R']),on=['競馬場','日付','R'],how='left')
result = historical_scores(target,horses,meta,pd.Timestamp(date))
st.subheader('過去走のみの分析（対象日より前・最大730日）')
st.dataframe(result,hide_index=True,use_container_width=True)
st.caption('暫定点は正式な100点評価ではありません。先行力・時計・展開は未評価。末脚は上がり順位でなく暫定代理指標です。')
st.caption('同名馬の混同可能性あり。馬IDが取得できれば馬IDに切り替えます。未来の着順・結果は過去走集計から除外しています。')
