"""Read saved pre-race runs only after recorded output hashes are verified."""
import hashlib
import json
from pathlib import Path
import pandas as pd

FILES={'ratings.csv','verified_entries.csv','scored_snapshot.csv'}

def list_runs(root):
    records=[]
    for path in sorted(Path(root).glob('*/*/*/run_manifest.json'),reverse=True):
        try:
            m=json.loads(path.read_text(encoding='utf-8'))
            records.append({'folder':str(path.parent),'status':m.get('status','unknown'),'venue':m.get('venue',''),'race':m.get('race',''),'started_at':m.get('started_at',''),'reason':m.get('reason','')})
        except (OSError,ValueError,TypeError):
            records.append({'folder':str(path.parent),'status':'unreadable','reason':'保存記録を読めません'})
    return records

def read_run(folder):
    folder=Path(folder);m=json.loads((folder/'run_manifest.json').read_text(encoding='utf-8'))
    if m.get('status')!='completed_prerace':raise ValueError('正常に完了した発走前評価ではありません')
    hashes=m.get('files',{})
    if set(hashes)!=FILES:raise ValueError('必要な出力ハッシュがありません')
    data={}
    for name in sorted(FILES):
        raw=(folder/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=hashes[name]:raise ValueError('保存後にファイルが変わっています: '+name)
        import io
        data[name]=pd.read_csv(io.BytesIO(raw),encoding='utf-8-sig')
    return m,data
