import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title='南関東競馬AI v0.1', page_icon='🏇', layout='wide')
st.title('🏇 南関東競馬AI v0.1')
st.caption('ルールベース試作版｜実際の出走表・オッズの自動取得や機械学習は未実装です')

FIELDS = {'適性':30, '先行力':20, '近走内容':20, '持ち時計':10, '末脚':15, '展開':5}
REQUIRED = ['日付','競馬場','R','馬番','馬名',*FIELDS]
VENUES = ['大井','船橋','川崎','浦和']

@st.cache_data
def demo():
    rows=[]
    for n in range(1,15):
        row={'日付':'2026-10-20','競馬場':'浦和','R':11,'馬番':n,'馬名':f'サンプル馬{n:02d}'}
        for j,(field,max_score) in enumerate(FIELDS.items()):
            row[field]=max(0, min(max_score, round(max_score*(0.45+((n*7+j*3)%13)/25))))
        rows.append(row)
    return pd.DataFrame(rows)

st.sidebar.header('設定')
venue=st.sidebar.selectbox('競馬場',VENUES,index=3)
budget=st.sidebar.number_input('1日の上限（円）',min_value=0,max_value=5000,value=5000,step=100)
st.sidebar.info('デモは架空の馬名・数値です。実際の購入判断には使わないでください。')

upload=st.file_uploader('出走馬CSVをアップロード（UTF-8）',type=['csv'])
try:
    df=pd.read_csv(upload,encoding='utf-8-sig') if upload else demo()
    missing=[x for x in REQUIRED if x not in df.columns]
    if missing: st.error('CSVに不足している列: '+', '.join(missing)); st.stop()
    df=df.copy()
    for field,limit in FIELDS.items():
        df[field]=pd.to_numeric(df[field],errors='coerce')
        if df[field].isna().any() or not df[field].between(0,limit).all():
            st.error(f'{field}は0〜{limit}の数値で入力してください');st.stop()
    df['馬番']=pd.to_numeric(df['馬番'],errors='raise').astype(int)
    df['R']=pd.to_numeric(df['R'],errors='raise').astype(int)
    df['評価点']=df[list(FIELDS)].sum(axis=1)
except Exception as e:
    st.error(f'CSVを読み込めません: {e}');st.stop()

sub=df[df['競馬場']==venue]
if sub.empty: st.warning('選択した競馬場のデータがありません');st.stop()
dates=sorted(sub['日付'].astype(str).unique().tolist())
date=st.selectbox('開催日',dates,index=len(dates)-1)
sub=sub[sub['日付'].astype(str)==date]
race=st.selectbox('レース',sorted(sub['R'].unique().tolist()))
race_df=sub[sub['R']==race].sort_values(['評価点','馬番'],ascending=[False,True]).reset_index(drop=True)
race_df.insert(0,'評価順位',range(1,len(race_df)+1))
st.subheader(f'{venue} {race}R：全頭評価')
st.dataframe(race_df[['評価順位','馬番','馬名','評価点',*FIELDS]],hide_index=True,use_container_width=True)
st.caption('点数は人手入力した6項目の合計。勝率・複勝率ではありません。')

st.subheader('買い目候補（参考）')
if len(race_df)>=2:
    a,b=race_df.iloc[0],race_df.iloc[1]
    st.write(f'評価上位2頭：{int(a["馬番"])}番 {a["馬名"]} ／ {int(b["馬番"])}番 {b["馬名"]}')
    st.warning('オッズと的中確率が未取得のため、期待値を判断できません。推奨購入額：0円（見送り）。')
else: st.info('2頭以上のデータが必要です。')
st.metric('本日の残予算（この画面内の仮計算）',f'{budget:,}円')

st.subheader('仮想馬券の結果検証')
st.caption('実購入の記録ではありません。入力値は画面を閉じると消える場合があります。')
with st.form('settlement'):
    ticket=st.selectbox('券種',['単勝','複勝','馬連','ワイド','三連複'])
    selection=st.text_input('買い目（例：3-7）')
    stake=st.number_input('投資額（円）',min_value=0,max_value=int(budget),step=100,value=0)
    payout=st.number_input('確定払戻額（円）',min_value=0,step=10,value=0)
    submitted=st.form_submit_button('収支を計算')
if submitted:
    if not selection.strip(): st.error('買い目を入力してください')
    else:
        profit=int(payout)-int(stake)
        roi=(payout/stake*100) if stake else 0
        st.metric('収支',f'{profit:+,}円')
        st.metric('回収率',f'{roi:.1f}%' if stake else '計算不可')
        result=pd.DataFrame([{'日付':date,'競馬場':venue,'R':race,'券種':ticket,'買い目':selection,'投資':stake,'払戻':payout,'収支':profit}])
        st.download_button('検証結果CSVを保存',result.to_csv(index=False).encode('utf-8-sig'),file_name='result.csv',mime='text/csv')

st.divider()
st.download_button('入力用CSV（デモ）を保存',demo().to_csv(index=False).encode('utf-8-sig'),file_name='sample_horses.csv',mime='text/csv')
st.caption('v0.1：データ永続化、リアルタイムオッズ、確率推定、発走前スナップショット、自動結果取得は未実装。')
