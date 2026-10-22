"""南関競馬AI v0.7 — GitHubに保存された公式ZIP/CSVを自動読込。"""
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import streamlit as st
from nar_import_v06 import read_uploads, historical_scores

st.set_page_config(page_title='南関競馬AI v0.7', layout='wide')
st.title('南関競馬AI v0.7')
st.caption('GitHub内の公式ZIP・CSVを自動読み込み。人気・オッズは能力評価に使用しません。')
st.info('過去結果データを分析する画面です。発走前出走表との接続、払戻検証済みモデルの運用は未実装です。表示の暫定点と nar_rating.py / nar_rating_v2.py の評価点は別方式です。')

@st.cache_data(show_spinner='保存済み競馬データを読み込み中…')
def load_local_data():
    root = Path(__file__).resolve().parent
    # リポジトリ直下、またはdata/に置かれた公式データを読む
    candidates = list(root.glob('*.zip')) + list(root.glob('*.csv')) + list((root / 'data').glob('*.zip')) + list((root / 'data').glob('*.csv'))
    # horselist / racelist / payback のいずれかを含む名前に限定
    candidates = sorted((p for p in candidates if any(x in p.name.lower() for x in ('race', 'horselist', 'racelist', 'payback'))), key=lambda p: str(p))
    sources = [SimpleNamespace(name=p.name, getvalue=lambda p=p: p.read_bytes()) for p in candidates]
    if not sources:
        return {}, ['GitHubに公式ZIP・CSVが見つかりません。'], []
    tables, notes = read_uploads(sources)
    return tables, notes, [str(p.relative_to(root)) for p in candidates]

if st.button('保存データを再読み込み'):
    load_local_data.clear()

tables, notes, filenames = load_local_data()
with st.expander('読み込んだファイル', expanded=False):
    st.write(filenames if filenames else 'なし')
for note in notes:
    st.warning(note)
if 'horselist' not in tables:
    st.error('horselistが見つかりません。公式レースZIPをGitHubに追加してください。')
    st.stop()
horses = tables['horselist']
st.success(f'出走データ {len(horses):,}件 / 対象期間 {horses["日付"].min().date()} ～ {horses["日付"].max().date()}')
venue = st.selectbox('競馬場', sorted(horses['競馬場'].unique()))
dates = sorted(horses.loc[horses['競馬場'] == venue, '日付'].dropna().unique(), reverse=True)
date = st.selectbox('開催日', dates, format_func=lambda x: pd.Timestamp(x).strftime('%Y-%m-%d'))
races = sorted(horses.loc[(horses['競馬場'] == venue) & (horses['日付'] == date), 'R'].dropna().unique())
race = st.selectbox('レース', races, format_func=lambda x: f'{int(x)}R')
target = horses[(horses['競馬場'] == venue) & (horses['日付'] == date) & (horses['R'] == race)].copy()
st.subheader('出走馬')
st.dataframe(target[[x for x in ['馬番', '馬名', '騎手名'] if x in target]], hide_index=True, use_container_width=True)
if 'racelist' not in tables:
    st.warning('racelistがないため距離別比較はできません。公式レースZIPを追加してください。')
    st.stop()
meta = tables['racelist']
if not {'距離', '馬場'}.issubset(meta.columns):
    st.warning('racelistに距離または馬場列がありません。')
    st.stop()
target = target.merge(meta[['競馬場', '日付', 'R', '距離', '馬場']].drop_duplicates(['競馬場', '日付', 'R']), on=['競馬場', '日付', 'R'], how='left')
result = historical_scores(target, horses, meta, pd.Timestamp(date))
st.subheader('過去走のみの分析（対象日より前・最大730日）')
st.dataframe(result, hide_index=True, use_container_width=True)
st.caption('暫定点であり正式な100点評価ではありません。先行力・時計・展開は未評価。末脚は暫定代理指標です。')
st.caption('同名馬を混同する可能性があります。馬ID取得後に改善します。未来のレース結果は過去走集計に使いません。')
