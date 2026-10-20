"""Download verified NAR monthly race archives from the official website.

Uses the publicly linked monthly RaceDataDownload endpoint. The endpoint may
change; non-ZIP responses are reported rather than stored as ZIPs.
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
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

BASE = 'https://www.keiba.go.jp'
ENDPOINT = BASE + '/KeibaWeb/DataDownload/RaceDataDownload'
UA = 'Mozilla/5.0 (compatible; NankanKeibaAI/1.0)'
MAX_BYTES = 50_000_000


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('a', 'form', 'button'):
            d = dict(attrs)
            for key in ('href', 'action', 'data-url', 'data-href'):
                if d.get(key):
                    self.urls.append(d[key])


def fetch(url):
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/zip,application/octet-stream,text/html,*/*'})
    with urlopen(req, timeout=40) as response:
        final = response.geturl()
        if urlparse(final).hostname not in ('www.keiba.go.jp', 'keiba.go.jp'):
            raise ValueError('Unexpected redirect host: ' + final)
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Response too large')
        return data


def valid_zip(data):
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return False
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            return False
        names = [Path(item.filename).name.lower() for item in archive.infolist()]
        return (any('horselist' in name and name.endswith('.csv') for name in names)
                and any('racelist' in name and name.endswith('.csv') for name in names))


def month_iter(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def shift_month(y, m, delta):
    v = y * 12 + m - 1 + delta
    return v // 12, v % 12 + 1


def candidates(y, m):
    page = ENDPOINT + '?' + urlencode({'type': 'monthly', 'k_year': y, 'k_month': m})
    # The official download URL may return the archive itself.
    data = fetch(page)
    if valid_zip(data):
        return data
    # Some versions return HTML with a link to the archive.
    if not data.lstrip().startswith((b'<!DOCTYPE', b'<!doctype', b'<html', b'<HTML')):
        raise ValueError('Official endpoint did not return a valid race ZIP or HTML')
    html = data.decode('utf-8', errors='replace')
    parser = Links()
    parser.feed(html)
    raw = parser.urls + re.findall(r'''["']([^"']+?\.zip(?:\?[^"']*)?)["']''', html, re.I)
    for item in raw:
        url = urljoin(page, item.replace('&amp;', '&'))
        if urlparse(url).hostname not in ('www.keiba.go.jp', 'keiba.go.jp'):
            continue
        if not re.search(r'\.zip(?:$|\?)', url, re.I) or re.search('odds?', url, re.I):
            continue
        try:
            result = fetch(url)
            if valid_zip(result):
                return result
        except Exception as exc:
            print('Candidate rejected:', type(exc).__name__, str(exc), file=sys.stderr)
    raise ValueError('No valid race ZIP found at official monthly download endpoint')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--months', type=int, default=24)
    parser.add_argument('--output', default='data')
    args = parser.parse_args()
    if not 1 <= args.months <= 120:
        parser.error('--months must be 1..120')
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    last = shift_month(today.year, today.month, -1)
    first = shift_month(*last, -(args.months - 1))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    failures = []
    for y, m in month_iter(first, last):
        prefix = f'{y}{m:02d}_'
        existing = list(output.glob(prefix + '*_race.zip')) + list(Path('.').glob(prefix + '*_race.zip'))
        if existing:
            print(f'SKIP {y}-{m:02d}: existing archive')
            continue
        try:
            data = candidates(y, m)
            name = f'{y}{m:02d}_official_race.zip'
            (output / name).write_bytes(data)
            print(f'SAVED {name}: {len(data)} bytes')
        except Exception as exc:
            msg = f'{y}-{m:02d}: {type(exc).__name__}: {exc}'
            failures.append(msg)
            print('FAILED', msg, file=sys.stderr)
        time.sleep(0.3)
    if failures:
        print('Uncollected months:\n' + '\n'.join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
