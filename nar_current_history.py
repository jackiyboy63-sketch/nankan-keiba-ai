"""Collect complete official race results before a prediction day; no same-day results.

Example: python nar_current_history.py --start 2026-10-01 --as-of 2026-10-26
Only complete, unique finishing orders are accepted. Special results are quarantined.
"""
import argparse
import hashlib
import io
import json
import re
import time
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse, parse_qs
import pandas as pd
from nar_capture import BASE, JST, VENUES, fetch
from nar_prerace_rating import parse_card, plain
from nar_validation import REQUIRED, prepare, validate_results


class ResultLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.urls.append(href)


def result_rows(html, day, venue, race, card):
    # Results headings omit the scheduled start time; do not infer it.
    text = plain(html)
    heading = f'{int(day[:4])}年{int(day[5:7])}月{int(day[8:])}日'
    if not re.search(re.escape(heading) + r'[（(][^）)]*[）)]' + re.escape(venue) + f'第{race}競走競走成績', text):
        raise ValueError('result race identity mismatch')
    distance = re.search(r'ダート(\d+)[ｍm]', text)
    going = re.search(r'馬場[：:](良|稍重|重|不良)', text)
    if not distance or not going:
        raise ValueError('result conditions missing')
    sections = re.findall(r'<section\b[^>]*class=["\']gradeTable["\'][^>]*>(.*?)</section>', html, re.S)
    if len(sections) != 1:
        raise ValueError('result table missing/ambiguous')
    rows = []
    tie_marked_ranks = set()
    identities = card.set_index('official_horse_id')
    for block in re.findall(r'<tr\b[^>]*class=["\']tBorder["\'][^>]*>(.*?)</tr>', sections[0], re.S):
        cells = {}
        for classes, content in re.findall(r'<td\b[^>]*class=["\']([^"\']+)["\'][^>]*>(.*?)</td>', block, re.S):
            cells[classes.split()[0]] = plain(content)
        ident = re.search(r'k_lineageLoginCode=(\d+)', unescape(block))
        if not ident or ident[1] not in identities.index:
            raise ValueError('result/card identity mismatch')
        e = identities.loc[ident[1]]
        if cells.get('d') != e['馬名'] or cells.get('c') != str(e['馬番']):
            raise ValueError('result/card runner mismatch')
        packed = re.fullmatch(r'(\d+):(\d{2})\.(\d)', cells.get('k', ''))
        if not packed or int(packed[2]) >= 60:
            raise ValueError('special/incomplete result time')
        row = {k: None for k in REQUIRED}
        row.update({k: e[k] for k in ['馬番', '馬名', 'horse_key', '父馬名', '母父馬名']})
        row.update(race_date=day, 競馬場=venue, レース番号=race,
                   距離=int(distance[1]), 馬場=going[1], 着順=cells.get('a'),
                   タイム=int(packed[1])*1000+int(packed[2])*10+int(packed[3]),
                   上がり3F=cells.get('m'), race_key=f'{venue}|{day.replace("-", "")}|{race}')
        if '同着' in cells.get('l', ''):
            tie_marked_ranks.add(cells.get('a'))
        rows.append(row)
    if len(rows) != len(card):
        raise ValueError('result/card runner set differs; quarantine scratches')
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError('no completed results')
    frame['頭数'] = len(frame)
    duplicate_ranks = set(frame.loc[frame['着順'].duplicated(keep=False), '着順'])
    if duplicate_ranks - tie_marked_ranks:
        raise ValueError('同着の明示がない順位重複')
    validate_results(prepare(frame), allow_dead_heats=True)
    return frame


def merge_history(base, supplement, as_of):
    """Reject future rows and conflicting overlaps; never silently replace archives."""
    cutoff = pd.Timestamp(as_of)
    for data in (base, supplement):
        if data.empty:
            continue
        d = prepare(data)
        if (d.race_date >= cutoff).any():
            raise ValueError('same-day/future history rejected')
    if supplement.empty:
        return base.copy()
    b = base.copy(); s = supplement.copy()
    def keys(d):
        return (pd.to_datetime(d.race_date).dt.strftime('%Y%m%d') + '|' +
                d['競馬場'].astype(str) + '|' + pd.to_numeric(d['レース番号']).astype(int).astype(str))
    b['_race'] = keys(b); s['_race'] = keys(s)
    for _, group in s.groupby('_race'):
        validate_results(prepare(group), allow_dead_heats=True)
    overlap = set(b._race) & set(s._race)
    compare = ['馬番', 'horse_key', '着順', 'タイム', '上がり3F', '距離', '馬場', '頭数']
    for race in overlap:
        def canonical(d):
            d = d.loc[d._race.eq(race), compare].copy()
            for c in compare:
                if c not in ('horse_key', '馬場'):
                    d[c] = pd.to_numeric(d[c], errors='coerce').astype(float)
            return d.sort_values('馬番').reset_index(drop=True)
        if not canonical(b).equals(canonical(s)):
            raise ValueError('conflicting archived/supplement race: ' + race)
    s = s[~s._race.isin(overlap)]
    # Canonical race key keeps race baselines whole even across source formats.
    out = pd.concat([b, s], ignore_index=True)
    out['race_key'] = out.pop('_race')
    prepare(out)
    return out


def collect(start, as_of, venues, output, fetcher=fetch, pause=time.sleep):
    start = pd.Timestamp(start).date(); end = pd.Timestamp(as_of).date()
    if not start <= end <= datetime.now(JST).date():
        raise ValueError('require start <= as-of <= today; same-day results are excluded')
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    frames = []; manifest = dict(as_of=end.isoformat(), start=start.isoformat(), pages=[], rejected=[], discovery_errors=[])
    def get(endpoint, day, venue, race=None):
        query = dict(k_raceDate=day.strftime('%Y/%m/%d'), k_babaCode=VENUES[venue])
        if race is not None: query['k_raceNo'] = race
        url = BASE + endpoint + '?' + urlencode(query)
        target = root/'sources'/day.isoformat()/str(VENUES[venue])/f'{endpoint}-{race or 0}.html'
        receipt_path = target.with_suffix('.json')
        cached = False
        if target.exists() and receipt_path.exists():
            record = json.loads(receipt_path.read_text())
            raw = target.read_bytes()
            received = datetime.fromisoformat(record['received_at'])
            if record['url'] != url or record['sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError('cached source integrity mismatch')
            cached = True
        else:
            raw, received, _ = fetcher(url)
        if received.tzinfo is None or received.astimezone(JST).date() <= day:
            raise ValueError('results must be retrieved on a later day')
        record = dict(path=str(target.relative_to(root)), url=url, received_at=received.isoformat(), sha256=hashlib.sha256(raw).hexdigest())
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        receipt_path.write_text(json.dumps(record), encoding='utf-8')
        manifest['pages'].append(record)
        if not cached: pause(2)
        return raw.decode('utf-8-sig')
    day = start
    while day < end:
        for venue in venues:
            try:
                listing = get('RaceList', day, venue)
                races = set()
                links = ResultLinks(); links.feed(listing)
                for href in links.urls:
                    u = urlparse(urljoin(BASE, unescape(href))); q = parse_qs(u.query)
                    if (u.hostname in ('www.keiba.go.jp', 'keiba.go.jp') and u.path.endswith('/RaceMarkTable') and
                        q.get('k_raceDate') == [day.strftime('%Y/%m/%d')] and q.get('k_babaCode') == [str(VENUES[venue])]):
                        n = int(q['k_raceNo'][0])
                        if 1 <= n <= 12: races.add(n)
                # No links is not proof of a non-racing day.
                if not races: raise ValueError('no verified result links; coverage unknown')
            except Exception as exc:
                manifest['discovery_errors'].append(dict(day=day.isoformat(), venue=venue, reason=str(exc)))
                continue
            for race in sorted(races):
                try:
                    card, _, _, _ = parse_card(get('DebaTable', day, venue, race), day.isoformat(), venue, race)
                    frames.append(result_rows(get('RaceMarkTable', day, venue, race), day.isoformat(), venue, race, card))
                except Exception as exc:
                    manifest['rejected'].append(dict(day=day.isoformat(), venue=venue, race=race, reason=str(exc)))
        day += timedelta(days=1)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=sorted(REQUIRED))
    if not data.empty: prepare(data)
    path = root/'current_history.csv'; data.to_csv(path, index=False, encoding='utf-8-sig')
    manifest.update(rows=len(data), races=len(frames), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    coverage='partial_or_unverified' if manifest['rejected'] or manifest['discovery_errors'] else 'verified_requested_links',
                    limitation='Retrospective official results, not historical pre-race snapshots; only dates before as_of.')
    (root/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return data, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start'); p.add_argument('--as-of', default=datetime.now(JST).date().isoformat())
    p.add_argument('--venue', action='append', choices=VENUES)
    p.add_argument('--output', default='data/current_results')
    p.add_argument('--base-history', default='data/processed/horse_history.csv')
    p.add_argument('--merged-output', default='data/processed/horse_history_current.csv')
    a = p.parse_args(); start = a.start or a.as_of[:8]+'01'
    data, manifest = collect(start, a.as_of, a.venue or list(VENUES), a.output)
    base = pd.read_csv(a.base_history, dtype={'生年月日':str}, low_memory=False)
    merged = merge_history(base, data, a.as_of)
    out = Path(a.merged_output); out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False, encoding='utf-8-sig')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('pages',)}, ensure_ascii=False))
    if data.empty and start != a.as_of: print('No verified supplements; base history only. Review manifest.')

if __name__ == '__main__': main()
