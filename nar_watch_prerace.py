"""Foreground, single-day pre-race archiver for Codespaces. No betting."""
import argparse
import fcntl
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from nar_capture import BASE, JST, VENUES, fetch, metadata
from nar_run_prerace import run
from nar_run_store import read_run


def save(path, state):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def discover(day, venue, fetcher=fetch, pause=time.sleep):
    races, errors = [], []
    for race in range(1, 13):
        query = urlencode(dict(k_raceDate=day.replace('-', '/'), k_babaCode=VENUES[venue], k_raceNo=race))
        try:
            raw, received, _ = fetcher(BASE + 'DebaTable?' + query)
            if received.tzinfo is None or received.astimezone(JST).date().isoformat() != day:
                raise ValueError('receipt date/time invalid')
            _, _, cutoff = metadata(raw.decode('utf-8-sig'), day, venue, race)
            races.append(dict(race=race, cutoff_at=cutoff.isoformat(), status='pending', attempts=0))
        except Exception as exc:
            errors.append(dict(race=race, reason=f'{type(exc).__name__}: {exc}'))
        if race < 12:
            pause(2)
    return dict(schema_version=1, day=day, venue=venue, races=races, discovery_errors=errors)


def reconcile(state, output):
    # Recover completed runs even after interruption between run() and state save.
    for row in state['races']:
        root = Path(output) / state['day'] / f"{VENUES[state['venue']]}-{row['race']:02d}"
        for manifest in sorted(root.glob('*/run_manifest.json'), reverse=True):
            try:
                m, _ = read_run(manifest.parent)
                expected = f"{state['day']}_{VENUES[state['venue']]}_{row['race']:02d}"
                if m.get('race_id') != expected:
                    continue
                row.update(status='completed', folder=str(manifest.parent))
                break
            except (OSError, ValueError, TypeError):
                continue


def tick(state, state_path, history, output, clock, runner=run):
    now = clock()
    if now.tzinfo is None:
        raise ValueError('clock timezone missing')
    if now.astimezone(JST).date().isoformat() != state['day']:
        raise ValueError('day changed; restart for the new day')
    for row in state['races']:
        if row['status'] in ('completed', 'missed', 'failed'):
            continue
        now = clock()  # refresh after a preceding race's slow network request
        cutoff = datetime.fromisoformat(row['cutoff_at'])
        if now >= cutoff - timedelta(minutes=1):
            row['status'] = 'missed'
            save(state_path, state)
            continue
        if now < cutoff - timedelta(minutes=5):
            continue
        last = row.get('last_attempt_at')
        if last and (now - datetime.fromisoformat(last)).total_seconds() < 60:
            continue
        if row['attempts'] >= 3:
            row['status'] = 'failed'
            save(state_path, state)
            continue
        row['attempts'] += 1
        row['last_attempt_at'] = now.isoformat()
        save(state_path, state)  # persist attempt before starting network work
        try:
            folder = runner(state['venue'], row['race'], history, output)
            row.update(status='completed', folder=str(folder))
            print(f"{state['venue']} {row['race']}R: 保存完了 {folder}", flush=True)
        except Exception as exc:
            row['reason'] = f'{type(exc).__name__}: {exc}'
            if row['attempts'] >= 3:
                row['status'] = 'failed'
            print(f"{row['race']}R: {row['reason']}", flush=True)
        save(state_path, state)
    return all(row['status'] in ('completed', 'missed', 'failed') for row in state['races'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--venue', required=True, choices=VENUES)
    p.add_argument('--history', default='data/processed/horse_history.csv')
    p.add_argument('--output', default='data/prerace_runs')
    p.add_argument('--state-dir', default='data/prerace_watch')
    a = p.parse_args()
    if not Path(a.history).is_file():
        p.error('history missing; prepare history in the screen first')
    day = datetime.now(JST).date().isoformat()
    root = Path(a.state_dir); root.mkdir(parents=True, exist_ok=True)
    path = root / f'{day}-{VENUES[a.venue]}.json'
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.error('another watcher is already running for this venue/day')
        if path.exists():
            state = json.loads(path.read_text(encoding='utf-8'))
            if state['day'] != day or state['venue'] != a.venue:
                raise ValueError('state identity mismatch')
        else:
            state = discover(day, a.venue)
            if not state['races']:
                save(path, state)
                raise SystemExit('No verified race schedule. Check venue/day and official pages; no monitoring started.')
            save(path, state)
        if not state['races']:
            raise SystemExit('No verified races in saved schedule. Review discovery errors before restarting.')
        print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
        print('取得できなかったRは監視対象外です。対象Rと時刻を上記で確認してください。', flush=True)
        reconcile(state, a.output); save(path, state)
        while not tick(state, path, a.history, a.output, lambda: datetime.now(timezone.utc)):
            time.sleep(30)
        print('本日の監視終了。結果は ' + str(path), flush=True)


if __name__ == '__main__':
    main()
