"""Bounded cloud session using existing verified capture/rating; no purchase."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from nar_capture import VENUES, JST
from nar_watch_prerace import discover, tick, save


def session(history='data/processed/horse_history.csv', output='data/prerace_runs', state_dir='data/prerace_watch', minutes=345, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic, pause=time.sleep, discoverer=discover, ticker=tick):
    if not 1 <= minutes <= 345:
        raise ValueError('session minutes must be 1..345')
    if not Path(history).is_file():
        raise ValueError('history missing')
    deadline = monotonic() + minutes*60
    day = clock().astimezone(JST).date().isoformat()
    root = Path(state_dir); root.mkdir(parents=True, exist_ok=True)
    states, errors = [], []
    # Explicitly record all venue failures; absence of parsable races is not proof of no meeting.
    for venue, code in VENUES.items():
        if monotonic() >= deadline:
            errors.append(dict(venue=venue,reason='session deadline before discovery'))
            continue
        print(f'{venue}: 当日出走表を確認中',flush=True)
        state = discoverer(day, venue)
        path = root/f'{day}-{code}.json'; save(path,state)
        if state['races']:
            states.append((state,path))
            print(f"{venue}: {len(state['races'])}R / 確認不能 {len(state['discovery_errors'])}R",flush=True)
        else:
            errors.append(dict(venue=venue,reason='no verified schedule',details=state['discovery_errors']))
    reason = 'all_verified_races_terminal'
    while states:
        if clock().astimezone(JST).date().isoformat() != day:
            reason='day_changed';break
        if monotonic() >= deadline:
            reason='session_deadline';break
        remaining=[]
        for state,path in states:
            if monotonic() >= deadline:
                remaining.append((state,path));continue
            if not ticker(state,path,history,output,clock):
                remaining.append((state,path))
        states=remaining
        if states:
            pause(min(30,max(0,deadline-monotonic())))
    summary=dict(day=day,ended_at=clock().isoformat(),reason=reason,unverified_venues=errors,
        pending_races=[dict(venue=s['venue'],race=r['race']) for s,_ in states for r in s['races'] if r['status']=='pending'],
        limitations=['Actions schedule can be delayed or dropped','no independent timestamp authentication','artifacts expire; download before retention ends','no betting or ROI proof'])
    (root/'cloud_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history',default='data/processed/horse_history.csv')
    p.add_argument('--minutes',type=int,default=345)
    a=p.parse_args();session(history=a.history,minutes=a.minutes)


if __name__=='__main__':main()
