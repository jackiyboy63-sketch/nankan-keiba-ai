"""Download monthly NAR race ZIP archives from publicly linked official pages.

Fail closed if a direct archive link cannot be found. No fabricated endpoints.
"""
import argparse
import datetime as dt
import io
import re
import sys
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

BASE = 'https://www.keiba.go.jp'
UA = 'nankan-keiba-ai/0.8 (monthly official archive downloader)'
MAX_BYTES = 50_000_000

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('a', 'button', 'form'):
            d = dict(attrs)
            for k in ('href', 'data-url', 'data-href', 'action'):
                if d.get(k):
                    self.urls.append(d[k])

def fetch(url):
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/zip,*/*'})
    with urlopen(req, timeout=30) as r:
        if urlparse(r.url).hostname not in ('www.keiba.go.jp', 'keiba.go.jp'):
            raise ValueError('Unexpected download host: ' + r.url)
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Archive exceeds size limit')
        return data

def month_iter(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

def month_before(d):
    return (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)

def shift_month(y, m, delta):
    v = y * 12 + m - 1 + delta
    return (v // 12, v % 12 + 1)

def discover(y, m):
    page = f'{BASE}/KeibaWeb/MonthlySchedule/MonthlyScheduleTop?k_year={y}&k_month={m}'
    html = fetch(page).decode('utf-8', errors='replace')
    parser = Links()
    parser.feed(html)
    # Also inspect script literals for ZIP URLs. Dynamic JS download APIs are
    # deliberately NOT guessed: unsupported months are reported for review.
    raw = parser.urls + re.findall(r'''["']([^"']+?\.zip(?:\?[^"']*)?)["']''', html, re.I)
    urls = []
    for s in raw:
        u = urljoin(page, s.replace('&amp;', '&'))
        parsed = urlparse(u)
        if parsed.hostname not in ('www.keiba.go.jp', 'keiba.go.jp'):
            continue
        if not re.search(r'\.zip(?:$|\?)', u, re.I):
            continue
        if re.search(r'odds?', u, re.I):
            continue
        if u not in urls:
            urls.append(u)
    return urls

def valid_zip(data):
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return False
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [x.filename.lower().split('/')[-1] for x in z.infolist()]
        return any('horselist' in n and n.endswith('.csv') for n in names) and any('racelist' in n and n.endswith('.csv') for n in names)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--months', type=int, default=24)
    p.add_argument('--output', default='data')
    args = p.parse_args()
    if not 1 <= args.months <= 120:
        p.error('--months must be between 1 and 120')
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    last = month_before(today)  # only completed calendar months
    first = shift_month(*last, -(args.months - 1))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    for y, m in month_iter(first, last):
        prefix = f'{y}{m:02d}_'
        existing = list(out.glob(prefix + '*_race.zip')) + list(Path('.').glob(prefix + '*_race.zip'))
        if existing:
            print(f'SKIP {y}-{m:02d}: already exists')
            continue
        try:
            candidates = discover(y, m)
            if not candidates:
                raise ValueError('No official ZIP link found in static monthly page (may be JavaScript-generated)')
            saved = False
            for url in candidates:
                try:
                    data = fetch(url)
                    if not valid_zip(data):
                        continue
                    name = Path(urlparse(url).path).name
                    if not re.fullmatch(r'\d{6}_\d+_race\.zip', name, re.I):
                        name = f'{y}{m:02d}_official_race.zip'
                    (out / name).write_bytes(data)
                    print(f'SAVED {name}: {len(data)} bytes')
                    saved = True
                    break
                except Exception as e:
                    print(f'Candidate failed: {type(e).__name__}: {e}')
            if not saved:
                raise ValueError('No valid race ZIP among discovered links')
        except Exception as e:
            failures.append(f'{y}-{m:02d}: {e}')
            print('FAILED', failures[-1], file=sys.stderr)
        time.sleep(0.4)
    if failures:
        print('\nUncollected months:\n' + '\n'.join(failures), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
