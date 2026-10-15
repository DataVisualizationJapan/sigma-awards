#!/usr/bin/env python3
"""Restore only image references present in the supplied DJA archive (requires Pillow)."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, unquote
from urllib.request import Request, urlopen

from PIL import Image
from dja.thumbnails import MANIFEST, ROOT, placeholder_reason, rejected_image_reason

DATA = ROOT / 'public/data/dja'
THUMBS = ROOT / 'public/thumbs/dja'
MAX_BYTES = 10 * 1024 * 1024
WAYBACK_LOCK = threading.Semaphore(2)
UA = 'DJAArchiveCatalog/1.0 (restoring images referenced in archived award pages)'


def http_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.netloc:
        raise ValueError('Not an HTTP image reference')
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe='/%:@!*+$,;=-_~()'),
                       quote(p.query, safe='=&%+/:?,@!*;$-_.~()'), ''))


def request(url, timeout):
    req = Request(http_url(url), headers={'User-Agent': UA, 'Accept': '*/*'})
    with urlopen(req, timeout=timeout) as response:
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('Image exceeds 10 MiB')
        return content, response.geturl()


def validate_image(content):
    """Reject HTML responses, tracking pixels, truncated files and unsupported formats."""
    reason = rejected_image_reason(hashlib.sha256(content).hexdigest())
    if reason:
        raise ValueError(reason)
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        fmt = image.format
        width, height = image.size
        if fmt not in ('PNG', 'JPEG', 'GIF', 'WEBP'):
            raise ValueError(f'Unsupported raster image format: {fmt}')
        if width < 64 or height < 48:
            raise ValueError('Image is too small to be an award thumbnail')
    return {'format': fmt, 'width': width, 'height': height}


def nearest_snapshots(reference, timeout):
    """CDX searches the referenced image path, allowing http/https and query-token variants."""
    p = urlsplit(reference['url'])
    # Query tokens often differ across snapshots; keep the exact image path.
    image_path = p.netloc + p.path
    params = [('url', image_path), ('matchType', 'prefix'), ('output', 'json'),
              ('filter', 'statuscode:200'), ('filter', 'mimetype:image/.*'),
              ('fl', 'timestamp,original'), ('collapse', 'digest')]
    content, _ = request('https://web.archive.org/cdx/search/cdx?' + urlencode(params), timeout)
    rows = json.loads(content)
    captures = []
    for stamp, original in rows[1:] if rows else []:
        original_p = urlsplit(original)
        if original_p.netloc.removeprefix('www.') != p.netloc.removeprefix('www.') or unquote(original_p.path) != unquote(p.path):
            continue
        captures.append((stamp, original))
    match = re.search(r'/web/(\d{14})', reference.get('pageSnapshot', ''))
    target = datetime.strptime(match[1], '%Y%m%d%H%M%S') if match else datetime(2019, 12, 31)
    captures.sort(key=lambda item: abs((datetime.strptime(item[0], '%Y%m%d%H%M%S') - target).total_seconds()))
    chosen = captures[:3]
    if captures:
        earliest = min(captures)
        if earliest not in chosen:
            chosen.append(earliest)
    return [f'https://web.archive.org/web/{stamp}id_/{original}' for stamp, original in chosen]


def restore(entry, details, previous, timeout):
    entry_id = entry['id']
    record = {'id': entry_id, 'year': entry['year'], 'title': entry['title'], 'attempts': []}
    refs = []
    excluded = []
    for ref in details.get('imageReferences', []):
        reason = placeholder_reason(ref['url'])
        if reason:
            excluded.append({'url': ref['url'], 'reason': reason})
        elif not any(r['url'] == ref['url'] for r in refs):
            refs.append(ref)
    record['excluded'] = excluded
    if previous and any(r['url'] == previous['sourceUrl'] and r['file'] == previous['sourceFile'] for r in refs):
        path = ROOT / 'public' / previous['path'].lstrip('/')
        if path.is_file() and not rejected_image_reason(previous['sha256']) and hashlib.sha256(path.read_bytes()).hexdigest() == previous['sha256']:
            record['status'] = 'adopted'
            record['cached'] = True
            return record, previous
    if not refs:
        record['status'] = 'excluded_placeholder' if excluded else 'no_reference'
        return record, None

    def fetch(reference, fetch_url, snapshot=''):
        try:
            content, resolved = request(fetch_url, timeout)
            metadata = validate_image(content)
            ext = {'PNG': 'png', 'JPEG': 'jpg', 'GIF': 'gif', 'WEBP': 'webp'}[metadata['format']]
            file = THUMBS / f'{entry_id}.{ext}'
            file.write_bytes(content)
            adopted = {**metadata, 'path': '/thumbs/dja/' + file.name, 'sourceUrl': reference['url'],
                       'sourceFile': reference['file'], 'pageSnapshot': reference.get('pageSnapshot', ''),
                       'retrievedUrl': resolved, 'snapshotUrl': snapshot,
                       'sha256': hashlib.sha256(content).hexdigest()}
            record['attempts'].append({'url': fetch_url, 'status': 'adopted'})
            record['status'] = 'adopted'
            return adopted
        except (HTTPError, URLError, ValueError, OSError, Image.DecompressionBombError) as error:
            record['attempts'].append({'url': fetch_url, 'status': 'failed', 'error': str(error)})
            if 'site placeholder' in str(error):
                record['excluded'].append({'url': fetch_url, 'reason': str(error)})
            return None

    # Try all explicit source references before issuing any archival lookups.
    for reference in refs:
        image = fetch(reference, reference['url'])
        if image:
            return record, image
    for reference in refs:
        with WAYBACK_LOCK:
            try:
                snapshots = nearest_snapshots(reference, timeout)
                record['attempts'].append({'url': reference['url'], 'status': 'archive_lookup', 'captures': len(snapshots)})
            except (HTTPError, URLError, ValueError, OSError) as error:
                record['attempts'].append({'url': reference['url'], 'status': 'archive_lookup_failed', 'error': str(error)})
                continue
            for snapshot in snapshots:
                image = fetch(reference, snapshot, snapshot)
                if image:
                    return record, image
    record['status'] = 'excluded_placeholder' if any('site placeholder' in e['reason'] for e in record['excluded']) else 'unavailable'
    return record, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    entries = json.loads((DATA / 'entries.json').read_text())['entries']
    details = {year: json.loads((DATA / f'details-{year}.json').read_text()) for year in range(2012, 2020)}
    previous = json.loads(MANIFEST.read_text())['images'] if MANIFEST.exists() else {}
    THUMBS.mkdir(parents=True, exist_ok=True)
    records = []
    images = dict(previous)

    def write_progress():
        MANIFEST.write_text(json.dumps({'images': dict(sorted(images.items()))}, ensure_ascii=False, indent=2) + '\n')
        counts = Counter(r['status'] for r in records)
        report = {'total': len(entries), 'processed': len(records), 'complete': len(records) == len(entries),
                  'counts': dict(sorted(counts.items())), 'records': sorted(records, key=lambda r: r['id'])}
        (DATA / 'thumbnails-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(restore, e, details[e['year']][e['id']], previous.get(e['id']), args.timeout): e for e in entries}
        for future in concurrent.futures.as_completed(futures):
            entry = futures[future]
            record, image = future.result()
            records.append(record)
            if image:
                images[entry['id']] = image
            else:
                images.pop(entry['id'], None)
            if record['status'] not in ('no_reference', 'excluded_placeholder'):
                print(entry['year'], record['status'], entry['title'][:85], flush=True)
            write_progress()
    print(json.dumps(dict(Counter(r['status'] for r in records)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
