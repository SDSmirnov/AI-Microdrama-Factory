"""One canonical-view map serves the video refs, panel QA and the disposition passes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.commands.screenplay import _resolve_anchor_ref
from lib.core.utils import canonical_ref_name, view_suffix


class CanonicalViewTests(unittest.TestCase):
    def test_derived_views_map_to_their_canonical(self):
        for slug, want in [('Flat-View-Center-To-Entrance', 'Flat-View-From-Entrance'),
                           ('Flat-View-To-Entrance', 'Flat-View-From-Entrance'),
                           ('Street-View-Ortho-Opposite', 'Street-View-Primary'),
                           ('Taxi-Interior-To-Entrance', 'Taxi-Interior-From-Entrance'),
                           ('Flat-View-From-Entrance', 'Flat-View-From-Entrance'),
                           ('Taxi-Exterior', 'Taxi-Exterior'),
                           ('Anna', 'Anna')]:
            self.assertEqual(canonical_ref_name(slug), want, slug)

    def test_longest_suffix_wins(self):
        self.assertEqual(view_suffix('Flat-View-Center-To-Entrance'), 'View-Center-To-Entrance')
        self.assertEqual(view_suffix('Street-View-Ortho-Opposite'), 'View-Ortho-Opposite')
        self.assertIsNone(view_suffix('Anna'))

    def test_anchor_ref_is_first_location_with_anchors(self):
        anchors = {'Flat-View-From-Entrance': {}, 'Street-View-Primary': {}}
        panel = {'location_references': ['Bar-View-To-Entrance', 'Street-View-Opposite', 'Flat-View-To-Entrance']}
        self.assertEqual(_resolve_anchor_ref(panel, anchors), 'Street-View-Primary')
        self.assertIsNone(_resolve_anchor_ref({'location_references': ['Taxi-Exterior']}, anchors))


if __name__ == '__main__':
    unittest.main()
