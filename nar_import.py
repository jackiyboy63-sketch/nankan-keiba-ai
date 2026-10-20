import io, zipfile, re
import pandas as pd
VENUES={'大井','船橋','川崎','浦和'}
NAMES={'racelist':'レース一覧','horselist':'出馬表','odds':'オッズ','payback':'払戻'}
COLUMNS={
'racelist':{0:'競馬場',1:'日付',2:'R',3:'発走時刻',5:'レース名',21:'芝ダート',22:'回り',23:'距離',24:'天候',25:'馬場',26:'頭数'},
'horselist':{0:'競馬場',1:'日付',2:'R',3:'枠番',5:'馬番',6:'馬名',14:'騎手',16:'斤量',24:'全成績',25:'左回り成績',26:'右回り成績',27:'当地成績',28:'当地距離成績',29:'最高タイム',30:'最高タイム良',31:'着順',32:'走破タイム',33:'着差',34:'上がり3F',35:'人気'},
'odds':{0:'競馬場',1:'日付',2:'R',3:'券種',4:'番号1',5:'番号2',6:'番号3',7:'オッズ',8:'最大オッズ',9:'人気'},
'payback':{0:'競馬場',1:'日付',2:'R',3:'レース名'}}

def parse_csv(data,kind):
    errors=[]
    for enc in ('utf-8-sig','cp932','utf-8'):
        try:
            # Official files have a header row; if they do not, detect by first field.
            raw=pd.read_csv(io.BytesIO(data),encoding=enc,header=None,dtype=str,low_memory=False).fillna('')
            if raw.empty:return pd.DataFrame()
            if str(raw.iloc[0,0]).strip().lstrip('\ufeff') in ('競馬場','競馬場名'):
                raw=raw.iloc[1:].reset_index(drop=True)
            mapping={k:v for k,v in COLUMNS[kind].items() if k in raw.columns}
            out=raw.rename(columns=mapping)
            out=out[[v for v in mapping.values()]]
            out=out[out['競馬場'].astype(str).str.strip().isin(VENUES)].copy()
            if not out.empty:
                out['日付']=out['日付'].astype(str).str.replace(r'\D','',regex=True).str[:8]
                out['R']=pd.to_numeric(out['R'],errors='coerce')
                out=out.dropna(subset=['R']);out['R']=out['R'].astype(int)
            return out
        except (UnicodeError,UnicodeDecodeError,pd.errors.ParserError) as e:errors.append(str(e))
    raise ValueError('CSVを解釈できません: '+str(errors[-1:]))

def read_zip(blob):
    result={}; found=[]
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for f in z.infolist():
            if f.is_dir() or f.file_size>70_000_000:continue
            name=f.filename.lower()
            kind=next((k for k in NAMES if re.search(r'(^|[/_])'+k+r'\.csv$',name)),None)
            if not kind:continue
            df=parse_csv(z.read(f),kind)
            if not df.empty:
                result.setdefault(kind,[]).append(df);found.append(f.filename)
    return {k:pd.concat(v,ignore_index=True).drop_duplicates() for k,v in result.items()},found
