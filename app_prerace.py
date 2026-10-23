"""Experimental pre-race capture/rating UI; separate from the historical app."""
from pathlib import Path
import subprocess
import sys
import pandas as pd
import streamlit as st
from nar_capture import VENUES,JST
from nar_run_prerace import run
from nar_run_store import list_runs,read_run

ROOT=Path(__file__).resolve().parent
HISTORY=ROOT/'data/processed/horse_history.csv'
RUNS=ROOT/'data/prerace_runs'
st.set_page_config(page_title='南関競馬AI 発走前検証',layout='wide')
st.title('南関競馬AI｜発走前検証')
st.caption('試作版 · 人気・オッズは能力評価に使用しません。購入判断はご自身で行ってください。')
st.info('評価点は的中確率ではありません。発走前の実地動作と収益性は検証中です。')
st.write('対象日：'+pd.Timestamp.now(tz=JST).strftime('%Y年%m月%d日（日本時間）'))

with st.expander('初回の履歴準備',expanded=not HISTORY.is_file()):
    st.write('保存済み公式ZIPから過去成績を作成します。ZIPを追加した後も、ここから更新できます。')
    if st.button('履歴を作成・更新'):
        with st.spinner('過去成績を準備しています…'):
            try:
                result=subprocess.run([sys.executable,str(ROOT/'nar_history.py'),'--input',str(ROOT),'--output',str(HISTORY.parent)],cwd=ROOT,capture_output=True,text=True,timeout=180)
                if result.returncode:st.error('履歴作成に失敗しました。');st.code(result.stderr[-3000:])
                else:st.success('履歴を準備しました。');st.text(result.stdout)
            except Exception as exc:st.error(str(exc))

with st.form('capture'):
    a,b=st.columns(2)
    venue=a.selectbox('競馬場',list(VENUES))
    race=b.number_input('レース',min_value=1,max_value=12,value=1,step=1)
    st.caption('当日・開催あり・発走前のレースを指定してください。取得後3分以内に評価と保存を完了できない場合は停止します。')
    submitted=st.form_submit_button('取得して評価を保存',disabled=not HISTORY.is_file())
if submitted:
    with st.spinner('出走表・単複オッズを取得し、過去成績と照合しています…'):
        try:
            folder=run(venue,int(race),HISTORY,RUNS)
            st.session_state['selected_run']=str(folder)
            st.success('取得・照合・評価・保存が完了しました。')
        except Exception as exc:st.error('完了できませんでした：'+str(exc))

st.subheader('保存済みの記録')
records=list_runs(RUNS)
if not records:
    st.write('まだ記録がありません。発走前のレースで取得を実行してください。')
else:
    options=[x['folder'] for x in records]
    lookup={x['folder']:x for x in records}
    selected=st.session_state.get('selected_run')
    selected=st.selectbox('記録を選択',options,index=options.index(selected) if selected in options else 0,format_func=lambda p: str(lookup[p].get('started_at',''))+'｜'+str(lookup[p].get('venue',''))+' '+str(lookup[p].get('race',''))+'R｜'+str(lookup[p]['status']))
    record=lookup[selected]
    if record['status']!='completed_prerace':
        st.warning('この記録は完了していません。');st.write(record.get('reason',''))
    else:
        try:
            manifest,tables=read_run(selected)
            st.caption('評価生成：'+manifest['score_generated_at']+'｜予定発走：'+manifest['cutoff_at'])
            ratings=tables['ratings.csv'].copy()
            ratings=ratings.rename(columns={'identity_status':'履歴照合','確かさ(%)':'評価材料の充足率(%)'})
            ratings['履歴照合']=ratings['履歴照合'].replace({'matched':'一致','unmatched':'未一致・未評価'})
            st.dataframe(ratings,hide_index=True,use_container_width=True)
            st.caption('充足率は取得できた評価材料の割合です。的中確率ではありません。')
            entries=tables['verified_entries.csv']
            with st.expander('取得時の単複オッズ'):
                cols=[c for c in ['馬番','馬名','status','win_odds','place_odds_low','place_odds_high'] if c in entries]
                st.dataframe(entries[cols].rename(columns={'status':'出走状態','win_odds':'単勝','place_odds_low':'複勝下限','place_odds_high':'複勝上限'}),hide_index=True,use_container_width=True)
                st.caption('取得時点の表示です。現在のオッズ・確定払戻とは異なる場合があります。')
            for name,label in [('ratings.csv','評価CSV'),('scored_snapshot.csv','検証用記録CSV')]:
                st.download_button(label,tables[name].to_csv(index=False).encode('utf-8-sig'),file_name=name,mime='text/csv')
        except Exception as exc:st.error('保存内容を確認できません：'+str(exc))
