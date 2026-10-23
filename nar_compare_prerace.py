"""Compare saved pre-race scores with imported monthly result history, without rerating."""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import numpy as np
import pandas as pd
from nar_capture import VENUES
from nar_prerace_rating import verify_capture
from nar_run_store import read_run
from nar_validation import prepare, validate_results


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compare(folder, results):
    folder = Path(folder)
    m, data = read_run(folder)
    capture_path = Path(m['capture_relative_path'])
    if capture_path.is_absolute() or '..' in capture_path.parts:
        raise ValueError('capture path invalid')
    capture_folder = folder / capture_path
    if digest((capture_folder/'manifest.json').read_bytes()) != m['capture_manifest_sha256']:
        raise ValueError('capture manifest hash mismatch')
    entries, _, _, source = verify_capture(capture_folder)
    if source['race_id'] != m['race_id']:
        raise ValueError('source/run race mismatch')
    cutoff = pd.Timestamp(source['cutoff_at'])
    times = [pd.Timestamp(m[k]) for k in ['started_at','score_generated_at','files_written_at']]
    receipt = pd.Timestamp(source['snapshot_at'])
    if any(t.tzinfo is None for t in [cutoff, receipt, *times]):
        raise ValueError('timezone missing')
    if not times[0] <= receipt <= times[1] <= times[2] < cutoff:
        raise ValueError('not a completed pre-race score')
    if cutoff != pd.Timestamp(m['cutoff_at']):
        raise ValueError('cutoff mismatch')
    day, venue, race = m['race_id'][:10], m['venue'], int(m['race'])
    if m['race_id'] != f'{day}_{VENUES[venue]}_{race:02d}':
        raise ValueError('race identity invalid')
    r = results[(results.race_date == pd.Timestamp(day)) & (results['競馬場'] == venue) & (pd.to_numeric(results['レース番号'], errors='coerce') == race)].copy()
    validate_results(r)  # conservative: no partial results, scratches, DNF or dead heats
    r['馬番'] = pd.to_numeric(r['馬番'], errors='raise').astype(int)
    if set(r['馬番']) != set(entries['馬番']):
        raise ValueError('result/source runner set differs')
    identity = entries[['馬番','馬名','horse_key']].merge(r[['馬番','馬名','horse_key']],on='馬番',suffixes=('_before','_result'),validate='one_to_one')
    if any(identity[k+'_before'].ne(identity[k+'_result']).any() for k in ['馬名','horse_key']):
        raise ValueError('result/source horse identity differs')
    if not entries.status.eq('active').all():
        raise ValueError('excluded runners require separate result rules')
    rating = data['ratings.csv'].copy()
    rating['馬番'] = pd.to_numeric(rating['馬番'],errors='raise')
    if rating['馬番'].duplicated().any() or set(rating['馬番']) != set(r['馬番']):
        raise ValueError('rating/result runner set differs')
    scored = rating[['馬番','馬名','評価点','確かさ(%)','identity_status']].merge(r[['馬番','馬名','着順_num']],on='馬番',suffixes=('','_result'),validate='one_to_one')
    if scored['馬名'].ne(scored['馬名_result']).any():
        raise ValueError('rating/result horse name differs')
    scores = pd.to_numeric(scored['評価点'],errors='raise')
    if np.isinf(scores).any() or scored.identity_status.isna().any() or not scored.identity_status.isin(['matched','unmatched']).all():
        raise ValueError('invalid score/identity status')
    if (scored.identity_status.eq('unmatched') & scores.notna()).any():
        raise ValueError('unmatched runner has a score')
    scored['評価点'] = scores
    # Shared score ranks preserve ties; all horses tied at the boundary are included.
    scored['事前評価順位'] = scores.rank(method='min',ascending=False)
    scored['実着順'] = scored['着順_num'].astype(int)
    scored['着順差_実着順マイナス評価順位'] = scored['実着順'] - scored['事前評価順位']
    top = scored[scored['事前評価順位'].le(3)]
    leaders = scored[scored['事前評価順位'].eq(1)]
    summary = dict(race_id=m['race_id'], runners=len(scored), scored_runners=int(scores.notna().sum()),
        top3_candidate_count=len(top), actual_top3_captured=int(top['実着順'].le(3).sum()),
        leader_count=len(leaders), leader_finishes=sorted(leaders['実着順'].tolist()),
        score_ties=bool(scores.dropna().duplicated().any()),
        note='同点は同順位。評価3位以内は同点次第で4頭以上。欠測は順位を付けない。収支は未計算。')
    return scored.drop(columns=['馬名_result','着順_num']).sort_values(['事前評価順位','馬番'],na_position='last'), summary


def report(runs, results_path, output='data/prerace_comparisons'):
    raw = Path(results_path).read_bytes()
    h = prepare(pd.read_csv(io.BytesIO(raw),encoding='utf-8-sig',low_memory=False))
    generated = datetime.now(timezone.utc)
    out = Path(output)/(generated.strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    out.mkdir(parents=True,exist_ok=False)
    accepted, skipped, files = [], [], {}
    # Use the earliest completed run per race; never select a snapshot by its result.
    candidates = []
    for path in sorted(Path(runs).glob('*/*/*/run_manifest.json')):
        try:
            m=json.loads(path.read_text(encoding='utf-8'))
            if m.get('status') != 'completed_prerace':
                continue
            t=pd.Timestamp(m['files_written_at'])
            if t.tzinfo is None:
                raise ValueError('timezone missing')
            candidates.append((t,str(path),m['race_id']))
        except Exception as exc:
            skipped.append(dict(folder=str(path.parent),reason=f'{type(exc).__name__}: {exc}'))
    selected=set()
    for _, path, race_id in sorted(candidates):
        if race_id in selected:
            continue
        selected.add(race_id)  # fail earliest invalid snapshot, do not cherry-pick another
        folder=Path(path).parent
        try:
            frame, summary=compare(folder,h)
            name=f'comparison-{len(accepted)+1:04d}.csv'
            frame.to_csv(out/name,index=False,encoding='utf-8-sig')
            files[name]=digest((out/name).read_bytes())
            summary['source_folder']=str(folder);summary['comparison_file']=name
            summary['source_manifest_sha256']=digest((folder/'run_manifest.json').read_bytes())
            accepted.append(summary)
        except Exception as exc:
            skipped.append(dict(folder=str(folder),race_id=race_id,reason=f'{type(exc).__name__}: {exc}'))
    summary=dict(schema_version=1, generated_at=generated.isoformat(), result_history_sha256=digest(raw),
        selection='earliest completed run by files_written_at; invalid earliest excluded',
        compared_races=len(accepted), skipped_races=len(skipped), races=accepted, skipped=skipped, files=files,
        limitations=['monthly imported results; official result fetching not included',
            'scratches, DNF, dead heats and partial result races excluded',
            'local clocks and hashes do not independently authenticate pre-race time',
            'no purchase records, payout or ROI calculation; no rerating or automatic model changes'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'照合 {len(accepted)}R / 除外 {len(skipped)}件: {out}')
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',default='data/prerace_runs')
    p.add_argument('--results',default='data/processed/horse_history.csv')
    p.add_argument('--output',default='data/prerace_comparisons')
    a=p.parse_args();report(a.runs,a.results,a.output)


if __name__=='__main__':
    main()
