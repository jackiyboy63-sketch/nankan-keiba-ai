import pandas as pd
import streamlit as st
from nar_import import read_zip, VENUES
st.set_page_config(page_title='南関東競馬AI v0.2',page_icon='🏇',layout='wide')
st.title('🏇 南関東競馬AI v0.2')
st.caption('NAR公式ZIP取込対応｜自動ダウンロード・機械学習・自動投票は未実装')
st.warning('この版はデータ確認用です。予測確率・期待値が未検証のため、推奨購入額は0円です。')
st.markdown('[NAR公式サイト](https://www.keiba.go.jp/) ／ [公式データ仕様書](https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf)')
st.info('NARパソコン版「本日のレース情報」または「月別開催日程」の下部から公式ZIPを取得し、下にアップロードしてください。')
files=st.file_uploader('NAR公式レース情報ZIP・オッズZIP（複数選択可）',type='zip',accept_multiple_files=True)
if not files:
    st.stop()
frames={}; seen=[]
for file in files:
    try:
        imported,names=read_zip(file.getvalue());seen+=names
        for kind,df in imported.items():frames.setdefault(kind,[]).append(df)
    except Exception as e:st.error(f'{file.name}: {e}')
frames={k:pd.concat(v,ignore_index=True).drop_duplicates() for k,v in frames.items()}
if not frames:
    st.error('公式CSVが見つかりません。_race.zip または _odds.zip を指定してください。');st.stop()
st.success('読み込み完了: '+', '.join(seen))
if 'horselist' not in frames:
    st.warning('出馬表がありません。レース情報ZIP（_race.zip）を追加してください。')
    for k,df in frames.items():st.write(k,len(df),'件')
    st.stop()
h=frames['horselist']; dates=sorted(h['日付'].dropna().unique().tolist())
venue=st.selectbox('競馬場',sorted(VENUES));date=st.selectbox('開催日',dates,index=len(dates)-1)
subset=h[(h['競馬場']==venue)&(h['日付']==date)]
if subset.empty:st.info('この競馬場・開催日のデータはありません。');st.stop()
race=st.selectbox('レース',sorted(subset['R'].unique().tolist()))
sub=subset[subset['R']==race].copy();sub['馬番数値']=pd.to_numeric(sub['馬番'],errors='coerce');sub=sub.sort_values('馬番数値')
if 'racelist' in frames:
    r=frames['racelist']; r=r[(r['競馬場']==venue)&(r['日付']==date)&(r['R']==race)]
    if not r.empty:
        x=r.iloc[0];st.subheader(f'{venue} {race}R  {x.get("レース名","")}');st.write('距離:',x.get('距離','不明'),'m｜馬場:',x.get('馬場','未発表'),'｜発走:',x.get('発走時刻','未確認'))
    else:st.subheader(f'{venue} {race}R')
else:st.subheader(f'{venue} {race}R')
st.dataframe(sub.drop(columns=['馬番数値']),hide_index=True,use_container_width=True)
if 'odds' in frames:
    odds=frames['odds']; odds=odds[(odds['競馬場']==venue)&(odds['日付']==date)&(odds['R']==race)]
    st.subheader('公式オッズ（ZIP取得時点）');st.dataframe(odds,hide_index=True,use_container_width=True)
else:st.info('オッズZIP未入力')
if 'payback' in frames:
    p=frames['payback'];p=p[(p['競馬場']==venue)&(p['日付']==date)&(p['R']==race)]
    if not p.empty:st.subheader('確定払戻（公式CSV原データの一部）');st.dataframe(p,hide_index=True,use_container_width=True)
st.subheader('評価・買い目')
st.warning('近走特徴量と予測モデルが未実装のため、購入判断は保留。推奨購入額 0円。')
st.download_button('表示中の出馬表をCSV保存',sub.drop(columns=['馬番数値']).to_csv(index=False).encode('utf-8-sig'),file_name='nankan_horses.csv',mime='text/csv')
st.caption('NARデータの利用・再配布には公式規約が適用されます。')
