"""Regression tests for archived facts, deduplication, and offline reproducibility."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_dja', ROOT / 'scripts/build-dja-data.py')
build_dja = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_dja)


class DjaDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((ROOT / 'public/data/dja/entries.json').read_text())
        cls.entries = cls.payload['entries']
        cls.details = {year: json.loads((ROOT / f'public/data/dja/details-{year}.json').read_text())
                       for year in cls.payload['years']}

    def entry(self, year, title):
        matches = [e for e in self.entries if e['year'] == year and e['title'] == title]
        self.assertEqual(len(matches), 1, (year, title))
        return matches[0]

    def test_catalog_integrity(self):
        build_dja.validate(self.entries, self.details)
        self.assertEqual(self.payload['years'], list(range(2012, 2020)))
        for year in self.payload['years']:
            yearly = [e for e in self.entries if e['year'] == year]
            self.assertTrue(yearly)
            self.assertTrue(all(e['result'] in ('winner', 'shortlist', 'mention') for e in yearly))
        self.assertTrue(any(not e['country'] for e in self.entries))
        self.assertTrue(any(not e['summary'] and not e['summaryJa'] for e in self.entries))
        self.assertFalse(any(e.get('thumb') for e in self.entries))

    def test_nominees_2013_are_73_distinct_targets(self):
        self.assertEqual(sum(e['year'] == 2013 for e in self.entries), 73)
        # Identically truncated titles belong to different archived submission IDs.
        mother_jones = [e for e in self.entries if e['year'] == 2013 and e['title'] == 'America Under the Gun:...']
        self.assertEqual(len(mother_jones), 2)
        self.assertNotEqual(mother_jones[0]['id'], mother_jones[1]['id'])
        title = self.entry(2013, 'Art Market for Dummies')
        self.assertEqual(sum(a['result'] == 'winner' for a in title['awards']), 2)

    def test_retrospective_years_and_same_category_history(self):
        row = self.entry(2016, 'The Panama Papers')
        self.assertEqual(row['result'], 'winner')
        self.assertEqual(len(row['awards']), 1)
        self.assertEqual({a['result'] for a in row['awards'][0]['evidence']}, {'winner', 'shortlist'})
        self.assertIn('2018/past-winners.html', [s['file'] for s in row['sources']])
        self.assertEqual(self.entry(2017, 'The Rhymes Behind Hamilton')['result'], 'winner')
        self.assertTrue(any(e['year'] == 2018 for e in self.entries))

    def test_shared_awards_are_not_separate_winners(self):
        row = self.entry(2015, 'Swiss Leaks / Luxembourg Leaks')
        self.assertEqual(row['result'], 'winner')
        records = self.details[2015][row['id']]['sourceRecords']
        self.assertTrue(any('Luxembourg Leaks' in r['text'] for r in records))
        self.assertTrue(any('Swiss Leaks' in r['text'] for r in records))
        self.entry(2015, 'Al Jazeera America — General Excellence')

    def test_incorrect_nos_profile_does_not_merge_the_pudding(self):
        nos = self.entry(2019, 'This is how thin you have to be, to walk the catwalk')
        pudding = self.entry(2019, 'The Pudding')
        self.assertNotEqual(nos['id'], pudding['id'])
        self.assertEqual(nos['org'], 'NOS')
        self.assertEqual(pudding['kind'], 'site')
        profiles = self.details[2019][nos['id']]['profileLinks']
        self.assertFalse(any('the-pudding' in u for u in profiles))
        self.assertEqual(sum(e['year'] == 2019 and e['result'] == 'winner' for e in self.entries), 12)

    def test_special_mentions_and_primary_results(self):
        for year, expected in [(2012, 3), (2018, 4), (2019, 1)]:
            self.assertEqual(sum(e['year'] == year and e['result'] == 'mention' for e in self.entries), expected)
        # It won Public Choice while remaining shortlisted in another category.
        row = self.entry(2017, 'Researchers bet on mass medication to wipe out malaria in L Victoria Region')
        self.assertEqual(row['result'], 'winner')
        self.assertTrue(any(a['result'] == 'shortlist' for a in row['awards']))

    def test_public_metadata_and_sources(self):
        self.assertNotIn('license', self.payload)
        for row in self.entries:
            self.assertTrue(all(not str(s).startswith('/Users/') for s in row['sources']))
            for source in row['sources']:
                self.assertTrue(source['file'].endswith('.html'))
                self.assertIn('original', source)
                self.assertIn('wayback', source)

    @unittest.skipUnless(build_dja.DEFAULT_SOURCE.exists(), 'Supplied archive is not installed')
    def test_rebuild_never_opens_network_and_is_deterministic(self):
        with patch('socket.create_connection', side_effect=AssertionError('Network is forbidden')):
            payload, details, report = build_dja.Catalog(build_dja.DEFAULT_SOURCE).build()
        self.assertEqual(payload, self.payload)
        self.assertEqual(details, self.details)
        self.assertEqual(report['htmlFiles'], 37)
        self.assertEqual(report['unusedCorrections'], [])
        self.assertEqual(report['decodingWarnings'], ['2013/wizehive-pages/page-3.html'])


if __name__ == '__main__':
    unittest.main()
