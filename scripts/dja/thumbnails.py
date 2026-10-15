"""Offline extraction and attachment of images referenced by the DJA archive."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

MANIFEST = Path(__file__).resolve().parent / 'thumbnails.json'
ROOT = Path(__file__).resolve().parents[2]
REJECTED_IMAGES = Path(__file__).resolve().parent / 'rejected-images.json'


def rejected_image_reason(digest):
    return json.loads(REJECTED_IMAGES.read_text()).get(digest, '')


def image_urls(node, base):
    """Prefer real lazy-loaded images over inline tracking/placeholder GIFs."""
    if node is None:
        return []
    urls = []
    for image in node.nodes('img'):
        src = image.attrs.get('data-lazy-src') or image.attrs.get('data-src') or image.attrs.get('src', '')
        if not src or src.startswith('data:'):
            continue
        url = urljoin(base, src)
        if urlsplit(url).scheme in ('http', 'https') and url not in urls:
            urls.append(url)
    return urls


def ancestor(node, cls):
    while node is not None:
        if node.has_class(cls):
            return node
        node = node.parent
    return None


def placeholder_reason(url):
    low = url.casefold()
    for part in ('project_default_image', '/default_images/', '/favicon', 'made_with_flourish', 'dja_website_bgimage', '/themes/den/images/logos/'):
        if part in low:
            return 'Generic placeholder or decorative image'
    return ''


def attach_thumbnails(entries, details, manifest_path=MANIFEST):
    """Only expose verified local files; never perform network I/O during builds."""
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    ids = {entry['id'] for entry in entries}
    unknown = set(manifest['images']) - ids
    if unknown:
        raise ValueError(f'Thumbnail manifest has unknown IDs: {sorted(unknown)}')
    for entry in entries:
        image = manifest['images'].get(entry['id'])
        if image is None:
            continue
        path = image['path']
        if not path.startswith('/thumbs/dja/') or '..' in Path(path).parts:
            raise ValueError(f'Invalid thumbnail path: {path}')
        source = image['sourceUrl']
        refs = details[entry['year']][entry['id']]['imageReferences']
        if not any(ref['url'] == source and ref['file'] == image['sourceFile'] for ref in refs):
            raise ValueError(f"Image has no matching archive reference: {entry['id']}")
        if rejected_image_reason(image['sha256']):
            raise ValueError(f"Rejected placeholder bytes: {entry['id']}")
        if placeholder_reason(source):
            raise ValueError(f'Placeholder in thumbnail manifest: {source}')
        file = ROOT / 'public' / path.lstrip('/')
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != image['sha256']:
            raise ValueError(f'Missing or modified thumbnail: {file}')
        entry['thumb'] = path
