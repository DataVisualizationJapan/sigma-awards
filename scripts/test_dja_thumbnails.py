"""Image-response and snapshot-selection tests; run with Pillow installed."""
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fetch_dja_thumbs', ROOT / 'scripts/fetch-dja-thumbs.py')
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class ImageTests(unittest.TestCase):
    def png(self, size):
        buffer = io.BytesIO()
        Image.new('RGB', size, '#123456').save(buffer, format='PNG')
        return buffer.getvalue()

    def test_reject_html_and_tracking_pixels(self):
        with self.assertRaises(OSError):
            fetch.validate_image(b'<html><title>Not an image</title></html>')
        with self.assertRaisesRegex(ValueError, 'too small'):
            fetch.validate_image(self.png((1, 1)))
        with self.assertRaises(OSError):
            fetch.validate_image(self.png((175, 175))[:30])
        self.assertEqual(fetch.validate_image(self.png((175, 175)))['width'], 175)

    def test_reject_known_placeholder_content(self):
        with patch.object(fetch, 'rejected_image_reason', return_value='DJA/DEN site placeholder'):
            with self.assertRaisesRegex(ValueError, 'site placeholder'):
                fetch.validate_image(self.png((500, 300)))

    def test_snapshot_lookup_does_not_match_other_image_paths(self):
        import json
        captures = [
            ['timestamp', 'original'],
            ['20190601000000', 'http://images.example.com/work.png?token=old'],
            ['20200405000000', 'https://images.example.com/work.png?token=new'],
            ['20200405000000', 'https://images.example.com/work.png.other'],
            ['20200405000000', 'https://other.example.com/work.png'],
        ]
        ref = {'url': 'http://images.example.com/work.png?token=original',
               'pageSnapshot': 'https://web.archive.org/web/20200401000000id_/http://example.com/'}
        with patch.object(fetch, 'request', return_value=(json.dumps(captures).encode(), '')):
            urls = fetch.nearest_snapshots(ref, 1)
        self.assertEqual(len(urls), 2)
        self.assertIn('/20200405000000id_/', urls[0])
        self.assertIn('/20190601000000id_/', urls[1])
        self.assertFalse(any('other' in url for url in urls))


if __name__ == '__main__':
    unittest.main()
