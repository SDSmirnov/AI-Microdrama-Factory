"""screenplay / scenes exit 2 on places without anchors; room QA records the judge that actually answered.

Oldie.Carp test run: View-Primary never passed QA, so the place had no anchors, and the screenplay still ran,
logging one warning per scene and writing every panel without blocking.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.commands.screenplay import _require_anchors
from lib.llm.manual import ManualLLM
from lib.studio.room_qa import _model_name, places_without_anchors

PLACES = {
    'Bar-View-From-Entrance': {'type': 'Room'},
    'Bar-View-To-Entrance': {'type': 'Room'},
    'Grounds-View-Primary': {'type': 'Outdoor'},
    'Grounds-View-Opposite': {'type': 'Outdoor'},
    'Kenno': {'type': 'Character'},
}


def project(tmp: Path, anchored: set[str]):
    for name in PLACES:
        data = {'anchor_points': {'objects': [{'id': 'x'}]}} if name in anchored else {}
        (tmp / f'{name.lower()}.json').write_text(json.dumps(data))
    return SimpleNamespace(ref_dir=tmp, character_info=PLACES, qa_model='', text_model='cfg/text')


class PlacesWithoutAnchorsTests(unittest.TestCase):
    def test_lists_truth_views_without_anchors_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project(Path(tmp), {'Bar-View-From-Entrance'})
            self.assertEqual(places_without_anchors(p), ['Grounds-View-Primary'])
            p = project(Path(tmp), {'Bar-View-From-Entrance', 'Grounds-View-Primary'})
            self.assertEqual(places_without_anchors(p), [])

    def test_screenplay_exits_2_unless_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project(Path(tmp), set())
            with self.assertRaises(SystemExit) as cm, self.assertLogs('lib.commands.screenplay', 'ERROR'):
                _require_anchors(p, SimpleNamespace(allow_missing_anchors=False))
            self.assertEqual(cm.exception.code, 2)
            with self.assertLogs('lib.commands.screenplay', 'WARNING'):
                _require_anchors(p, SimpleNamespace(allow_missing_anchors=True))
            _require_anchors(project(Path(tmp), {'Bar-View-From-Entrance', 'Grounds-View-Primary'}),
                             SimpleNamespace(allow_missing_anchors=False))


class QaModelNameTests(unittest.TestCase):
    def test_records_the_backend_that_answered(self):
        p = SimpleNamespace(qa_model='', text_model='cfg/text')
        self.assertEqual(_model_name(SimpleNamespace(text_model='google/gemini-3.8-flash'), p, 'judge'),
                         'google/gemini-3.8-flash')
        self.assertEqual(_model_name(ManualLLM(), p, 'google/gemini-3.8-flash'), 'ManualLLM')
        self.assertEqual(_model_name(object(), p, 'judge'), 'judge')
        self.assertEqual(_model_name(object(), p), 'cfg/text')


if __name__ == '__main__':
    unittest.main()
