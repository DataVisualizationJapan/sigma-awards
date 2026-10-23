"""Tests for the Sigma ID ledger: IDs must survive upstream edits."""
import copy
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from sigma import ledger as L  # noqa: E402

spec = importlib.util.spec_from_file_location('build_sigma', ROOT / 'scripts/build-data.py')
build_sigma = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_sigma)

UPSTREAM = ROOT / '.tmp-data'
PINNED = '311fc0c'
PORTFOLIOS_2020 = 'The Sigma Awards 2020-portfolios.csv'


def make_row(n, **extra):
    row = {
        'Project title': f'Investigation number {n}',
        'Publishing organisations': f'Newsroom {n}',
        'Category': '',
        'A short description of the project': f'A long description of story {n} with unique words w{n}x',
        'Project link 1': f'https://example.org/story-{n}',
        'Project link 2': f'https://example.org/data-{n}',
        'Results': '',
    }
    row.update(extra)
    return row


def make_rows(count):
    return [make_row(n) for n in range(1, count + 1)]


def run(ledger, rows, year=2024, kind='project'):
    ids, report = L.reconcile(ledger, year, kind, copy.deepcopy(rows))
    return ids, report


def fresh(rows, **kw):
    ledger = L.empty_ledger()
    ids, _ = run(ledger, rows, **kw)
    return ledger, ids


class LedgerTests(unittest.TestCase):
    def test_bootstrap_numbers_rows_in_order(self):
        _, ids = fresh(make_rows(3))
        self.assertEqual(ids, ['2024-s-0001', '2024-s-0002', '2024-s-0003'])
        _, ids = fresh(make_rows(2), year=2020, kind='portfolio')
        self.assertEqual(ids, ['2020-f-0001', '2020-f-0002'])

    def test_rerun_is_stable(self):
        rows = make_rows(30)
        ledger, ids = fresh(rows)
        again, report = run(ledger, rows)
        self.assertEqual(again, ids)
        self.assertEqual(len(report['confirmed']), 30)
        self.assertFalse(report['scored'] or report['new'] or report['removed'])

    def test_shuffle_keeps_ids_attached_to_rows(self):
        rows = make_rows(40)
        ledger, ids = fresh(rows)
        by_title = {r['Project title']: i for r, i in zip(rows, ids)}
        shuffled = rows[:]
        random.Random(1).shuffle(shuffled)
        again, _ = run(ledger, shuffled)
        self.assertEqual(again, [by_title[r['Project title']] for r in shuffled])

    def test_insert_at_front_and_delete_in_middle_never_reuse_ids(self):
        rows = make_rows(10)
        ledger, ids = fresh(rows)
        by_title = {r['Project title']: i for r, i in zip(rows, ids)}
        edited = [make_row(99)] + [r for r in rows if r['Project title'] != 'Investigation number 4']
        again, report = run(ledger, edited)
        self.assertEqual(again[0], '2024-s-0011')
        self.assertEqual(again[1:], [by_title[r['Project title']] for r in edited[1:]])
        self.assertEqual(report['removed'], ['2024-s-0004'])
        self.assertTrue(ledger['entries']['2024-s-0004']['removed'])
        # Both the freed number and a later arrival must stay unique.
        again, _ = run(ledger, edited + [make_row(100)])
        self.assertEqual(again[-1], '2024-s-0012')
        self.assertNotIn('2024-s-0004', again)

    def test_removed_tail_number_is_not_reused(self):
        rows = make_rows(5)
        ledger, _ = fresh(rows)
        run(ledger, rows[:4])
        again, _ = run(ledger, rows[:4] + [make_row(50)])
        self.assertEqual(again[-1], '2024-s-0006')

    def test_removed_entry_can_return(self):
        rows = make_rows(5)
        ledger, ids = fresh(rows)
        run(ledger, rows[:2] + rows[3:])
        again, _ = run(ledger, rows)
        self.assertEqual(again, ids)
        self.assertFalse(ledger['entries'][ids[2]]['removed'])

    def test_title_edit(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[7]['Project title'] = 'Investigation number 8, revised'
        again, report = run(ledger, rows)
        self.assertEqual(again, ids)
        self.assertEqual([i for i, _ in report['scored']], [ids[7]])

    def test_org_edit(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[3]['Publishing organisations'] = 'Newsroom 4 (renamed)'
        again, report = run(ledger, rows)
        self.assertEqual(again, ids)
        self.assertEqual(len(report['scored']), 1)

    def test_link_edit(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[11]['Project link 1'] = 'https://example.org/moved-12'
        again, report = run(ledger, rows)
        self.assertEqual(again, ids)
        self.assertEqual(len(report['scored']), 1)

    def test_description_edit(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[0]['A short description of the project'] = 'Completely rewritten text'
        again, _ = run(ledger, rows)
        self.assertEqual(again, ids)

    def test_edit_follows_across_repeated_builds(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[5]['Project title'] = 'First edit'
        run(ledger, rows)
        rows[5]['Publishing organisations'] = 'Second edit'
        again, _ = run(ledger, rows)
        self.assertEqual(again, ids)

    def test_2020_category_duplicates_keep_distinct_ids(self):
        cats = ['Data visualization', 'Investigation', 'Innovation']
        rows = [make_row(1, Category=c) for c in cats] + make_rows(5)[1:]
        ledger, ids = fresh(rows, year=2020)
        self.assertEqual(len(set(ids[:3])), 3)
        by_cat = dict(zip(cats, ids[:3]))
        shuffled = rows[:]
        random.Random(3).shuffle(shuffled)
        again, report = run(ledger, shuffled, year=2020)
        for row, entry_id in zip(shuffled, again):
            if row['Category']:
                self.assertEqual(entry_id, by_cat[row['Category']])
        self.assertFalse(report['scored'])

    def test_2020_duplicate_with_edited_description_is_resolved_by_category(self):
        cats = ['Data visualization', 'Investigation', 'Innovation']
        rows = [make_row(1, Category=c) for c in cats] + make_rows(5)[1:]
        ledger, ids = fresh(rows, year=2020)
        rows[1]['A short description of the project'] = 'Rewritten'
        again, _ = run(ledger, rows, year=2020)
        self.assertEqual(again, ids)

    def test_case_only_duplicates_are_kept_apart(self):
        a = make_row(1)
        b = make_row(1, **{'Project title': 'INVESTIGATION NUMBER 1',
                           'A short description of the project': 'Another text, same title'})
        rows = [a, b] + make_rows(6)[1:]
        ledger, ids = fresh(rows)
        self.assertEqual(len(set(ids)), len(ids))
        again, report = run(ledger, rows[::-1])
        self.assertEqual(again, ids[::-1])
        self.assertFalse(report['scored'])

    def test_case_only_difference_in_title_still_matches(self):
        rows = make_rows(20)
        ledger, ids = fresh(rows)
        rows[2]['Project title'] = rows[2]['Project title'].upper()
        again, _ = run(ledger, rows)
        self.assertEqual(again, ids)

    def test_ambiguous_tie_stops_the_build(self):
        # Two ledger entries differ only in Category; upstream collapses to one edited row
        # that matches both equally well.
        rows = [make_row(1, Category='A'), make_row(1, Category='B')] + make_rows(8)[1:]
        ledger, _ = fresh(rows, year=2020)
        edited = [make_row(1, Category='C')] + make_rows(8)[1:]
        edited[0]['A short description of the project'] = rows[0]['A short description of the project']
        edited[0]['Publishing organisations'] = 'Someone else'
        with self.assertRaises(L.LedgerError) as caught:
            run(ledger, edited, year=2020)
        self.assertIn('overrides', str(caught.exception))

    def test_too_many_scored_matches_stop_the_build(self):
        rows = make_rows(60)
        ledger, _ = fresh(rows)
        for row in rows[:L.SCORE_LIMIT_MAX + 1]:
            row['Project title'] += ' (edited)'
        with self.assertRaises(L.LedgerError) as caught:
            run(ledger, rows)
        self.assertIn('limit', str(caught.exception))

    def test_failed_match_does_not_touch_entries_it_did_not_resolve(self):
        rows = make_rows(60)
        ledger, ids = fresh(rows)
        for row in rows[:25]:
            row['Project title'] += ' (edited)'
        try:
            run(ledger, rows)
        except L.LedgerError:
            pass
        # build-data.py only saves the ledger after every group succeeds.
        self.assertEqual(set(ledger['entries']), set(ids))

    def test_override_pins_an_id(self):
        rows = [make_row(1, Category='A'), make_row(1, Category='B')] + make_rows(8)[1:]
        ledger, ids = fresh(rows, year=2020)
        edited = [make_row(1, Category='C')] + make_rows(8)[1:]
        edited[0]['A short description of the project'] = rows[0]['A short description of the project']
        edited[0]['Publishing organisations'] = 'Someone else'
        ledger['overrides'][ids[1]] = L.fingerprint(edited[0])['rowHash']
        again, report = run(ledger, edited, year=2020)
        self.assertEqual(again[0], ids[1])
        self.assertEqual(report['overrides'], [ids[1]])
        self.assertEqual(report['removed'], [ids[0]])

    def test_overrides_for_other_groups_are_ignored(self):
        rows = make_rows(5)
        ledger, ids = fresh(rows)
        ledger['overrides']['2021-s-0001'] = 'deadbeef'
        again, _ = run(ledger, rows)
        self.assertEqual(again, ids)

    def test_unrelated_rows_become_new_not_scored(self):
        rows = make_rows(10)
        ledger, ids = fresh(rows)
        again, report = run(ledger, rows[:5] + [make_row(200), make_row(201)])
        self.assertEqual(again[:5], ids[:5])
        self.assertEqual(report['new'], ['2024-s-0011', '2024-s-0012'])
        self.assertEqual(len(report['removed']), 5)

    def test_groups_are_independent(self):
        rows = make_rows(3)
        ledger, _ = fresh(rows, year=2024)
        ids, _ = run(ledger, rows, year=2025)
        self.assertEqual(ids[0], '2025-s-0001')
        ids, _ = run(ledger, rows, year=2024, kind='portfolio')
        self.assertEqual(ids[0], '2024-f-0001')

    def test_save_and_load_roundtrip(self):
        ledger, _ = fresh(make_rows(3))
        ledger['upstreamCommit'] = 'abc'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ids.json'
            L.save(ledger, path)
            self.assertEqual(L.load(path), ledger)
            self.assertEqual(json.loads(path.read_text()), ledger)


def git(*args):
    return subprocess.run(['git', '-C', str(UPSTREAM), *args], capture_output=True, check=True).stdout


def upstream_has(*revs):
    if not (UPSTREAM / '.git').exists():
        return False
    return all(subprocess.run(['git', '-C', str(UPSTREAM), 'cat-file', '-e', r + '^{commit}']).returncode == 0
               for r in revs)


def rows_at(rev, filename):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_bytes(git('show', f'{rev}:{filename}'))
        return [r for r in build_sigma.load_rows(path) if build_sigma.first(r.get('Project title'))]


@unittest.skipUnless(upstream_has(PINNED), 'upstream clone with 311fc0c not available in .tmp-data')
class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((ROOT / 'public/data/entries.json').read_text())
        cls.ledger = L.load()
        cls.groups = {}
        for year, filename, kind in build_sigma.FILES:
            cls.groups[(year, kind)] = rows_at(PINNED, filename)

    def test_every_published_id_is_in_the_ledger(self):
        entries = self.ledger['entries']
        ids = [e['id'] for e in self.payload['entries']]
        self.assertEqual(len(ids), 3899)
        self.assertTrue(all(i in entries and not entries[i]['removed'] for i in ids))
        self.assertEqual(len(entries), len(ids))

    def test_ledger_commit_is_recorded(self):
        self.assertTrue(self.ledger['upstreamCommit'])
        self.assertTrue(self.payload['upstreamCommit'])

    def test_regenerating_from_311fc0c_keeps_every_id(self):
        published = {}
        for e in self.payload['entries']:
            published.setdefault((e['year'], e['kind']), []).append(e['id'])
        for fresh_ledger in (L.empty_ledger(), copy.deepcopy(self.ledger)):
            for (year, kind), rows in self.groups.items():
                ids, report = L.reconcile(fresh_ledger, year, kind, rows)
                self.assertEqual(ids, published[(year, kind)], (year, kind))
                self.assertFalse(report['scored'] or report['removed'])

    def test_every_year_kind_group_is_present(self):
        self.assertEqual(sum(len(r) for r in self.groups.values()), 3899)

    @unittest.skipUnless(upstream_has('dc71023^', 'dc71023'), 'dc71023 not in clone')
    def test_applicant_removal_dc71023_removes_one_and_keeps_the_rest(self):
        before = rows_at('dc71023^', PORTFOLIOS_2020)
        after = rows_at('dc71023', PORTFOLIOS_2020)
        self.assertEqual(len(before) - len(after), 1)
        ledger = L.empty_ledger()
        ids_before, _ = L.reconcile(ledger, 2020, 'portfolio', before)
        ids_after, report = L.reconcile(ledger, 2020, 'portfolio', after)
        gone = set(ids_before) - set(ids_after)
        self.assertEqual(len(gone), 1)
        self.assertEqual(report['removed'], list(gone))
        self.assertEqual(report['new'], [])
        self.assertFalse(report['scored'])
        removed_index = ids_before.index(gone.pop())
        self.assertEqual(ids_after, ids_before[:removed_index] + ids_before[removed_index + 1:])
        self.assertTrue(removed_index < len(ids_after))  # later IDs did not shift


if __name__ == '__main__':
    unittest.main()
