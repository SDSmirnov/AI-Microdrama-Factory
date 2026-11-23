"""Model-written ref names ('Kennō', 'Bodyguard-2', 'Blind-Musician-1') resolve to the cast refs before and at render.

Oldie.Carp test run: the screenplay wrote these spellings, renders matched names exactly, and no person's card
reached the grid prompt.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.archivist import match_ref
from lib.studio.artist.render_utils import _ref_label, known_refs
from lib.studio.critic import find_ref
from lib.studio.screenwriter.enforce import (
    _enforce_lint, canonical_contract, canonical_panel_refs, canonical_refs, unknown_ref_issues,
)

REFS = {n: {} for n in ('Kenno', 'Bodyguard', 'Blind-Musicians', 'Amida-Buddha', 'Muramasa-Sword',
                        'Hongan-Ji-Grounds-View-Primary')}


def state(*actors):
    return {'panels': [{'panel_index': 1, 'state': {'actors': [
        {'name': n, 'visual_ref': v} for n, v in actors]}}]}


def vrefs(p1a):
    return [a['visual_ref'] for a in p1a['panels'][0]['state']['actors']]


class MatchRefTests(unittest.TestCase):
    def test_spelling_variants_resolve(self):
        for name, ref in [('Kenno', 'Kenno'), ('Kennō', 'Kenno'), ('kenno', 'Kenno'), ('Bodyguard-2', 'Bodyguard'),
                          ('Blind-Musician-1', 'Blind-Musicians'), ('Blind Musicians', 'Blind-Musicians'),
                          ('Hongan-Ji-Grounds-View-Primary', 'Hongan-Ji-Grounds-View-Primary')]:
            self.assertEqual(match_ref(name, REFS), ref, name)

    def test_other_names_do_not(self):
        for name in ('Amitabha', 'Prayer beads', '', 'Ken'):
            self.assertIsNone(match_ref(name, REFS), name)

    def test_find_ref_falls_back_to_match_ref(self):
        catalog = {'Kenno': {'id': 1}}
        self.assertEqual(find_ref('Kennō', catalog), {'id': 1})
        self.assertIsNone(find_ref('Amitabha', catalog))


class CanonicalRefsTests(unittest.TestCase):
    def test_visual_refs_rewritten_names_kept(self):
        p1a = canonical_refs(state(('Kennō', 'Kennō'), ('Bodyguard-1', ''), ('Passer-by', '')), REFS)
        self.assertEqual(vrefs(p1a), ['Kenno', 'Bodyguard', ''])
        self.assertEqual([a['name'] for a in p1a['panels'][0]['state']['actors']], ['Kennō', 'Bodyguard-1', 'Passer-by'])
        self.assertIsNone(canonical_refs(None, REFS))

    def test_unknown_refs_are_issues_extras_are_not(self):
        p1a = canonical_refs(state(('Amitabha', 'Amitabha'), ('Passer-by', ''), ('Kennō', '')), REFS)
        issues = unknown_ref_issues(p1a, REFS)
        self.assertEqual(len(issues), 1)
        self.assertIn("'Amitabha'", issues[0])

    def test_unknown_ref_triggers_one_retry(self):
        bad, good = state(('Amitabha', 'Amitabha')), state(('Amida', 'Amida-Buddha'))
        seen = []
        out = _enforce_lint(bad, lambda c: seen.append(c) or good, lambda r: unknown_ref_issues(r, REFS), 'Pass 1A refs')
        self.assertIs(out, good)
        self.assertIn('Amitabha', seen[0])

    def test_contract_and_panel_references(self):
        spec = {'entry_state': [{'character': 'Kennō', 'visual_ref': 'Kennō'}], 'exit_state': None}
        canonical_contract(spec, REFS)
        self.assertEqual(spec['entry_state'][0]['visual_ref'], 'Kenno')
        merged = {'panels': [{'references': ['Kennō', 'Bodyguard-1', 'Bodyguard-2', 'Prayer beads'],
                              'location_references': ['Hongan-Ji-Grounds-View-Primary']}]}
        canonical_panel_refs(merged, REFS)
        self.assertEqual(merged['panels'][0]['references'], ['Kenno', 'Bodyguard', 'Prayer beads'])
        self.assertEqual(merged['panels'][0]['location_references'], ['Hongan-Ji-Grounds-View-Primary'])


class RenderRefsTests(unittest.TestCase):
    def test_known_refs_resolves_dedupes_and_drops_unknown(self):
        with self.assertLogs('lib.studio.artist.render_utils', 'WARNING') as log:
            self.assertEqual(known_refs(['Kennō', 'Kenno', 'Bodyguard-1', 'Blood on grass'], REFS),
                             ['Kenno', 'Bodyguard'])
        self.assertIn('Blood on grass', log.output[0])

    def test_outdoor_ref_is_labelled_as_environment(self):
        label = _ref_label('Hongan-Ji-Grounds-View-Primary', 'Outdoor', '')
        self.assertIn('SCENE ENVIRONMENT', label)
        self.assertNotIn('CHARACTER', label)


if __name__ == '__main__':
    unittest.main()
