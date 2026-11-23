"""detail-rooms: draft → self-critique for both the vocabulary and every view."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project
from lib.core.schemas import (
    ROOM_DETAIL_CRITIQUE_SCHEMA, ROOM_DETAIL_SCHEMA,
    ROOM_VOCABULARY_CRITIQUE_SCHEMA, ROOM_VOCABULARY_SCHEMA,
)
from lib.studio.artist import _ROOM_VIEWS, detail_room_refs
from lib.studio.room_geometry import BEHIND_CAMERA

DRAFT_VOCAB = [
    {'id': 'server-rack-row', 'description': 'Racks along the left wall.'},
    {'id': 'side-door', 'description': 'A second door on the left wall.'},  # invented
]
CLEAN_VOCAB = DRAFT_VOCAB[:1]


class FakeLLM:
    def __init__(self, critic_ok=True):
        self.critic_ok = critic_ok
        self.calls = []

    def make_json(self, prompt, schema):
        self.calls.append((schema, prompt))
        if schema is ROOM_VOCABULARY_SCHEMA:
            return {'named_positions': DRAFT_VOCAB}
        if schema is ROOM_VOCABULARY_CRITIQUE_SCHEMA:
            if not self.critic_ok:
                return None
            return {'issues': ['side-door: not in story; remove'], 'named_positions': CLEAN_VOCAB}
        if schema is ROOM_DETAIL_SCHEMA:
            return {'enriched_visual_desc': 'Draft without ids.'}
        if schema is ROOM_DETAIL_CRITIQUE_SCHEMA:
            if not self.critic_ok:
                return None
            return {'issues': ['missing server-rack-row'],
                    'revised_visual_desc': 'Racks `server-rack-row` image-left. Empty room.'}
        raise AssertionError(schema)


class DetailRoomsCritiqueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Project()
        self.project.ref_dir = Path(tmp.name)
        self.project.max_workers = 1
        self.vfe = self.project.ref_dir / 'hold-view-from-entrance.json'
        self.vfe.write_text(json.dumps({
            'name': 'Hold-View-From-Entrance', 'type': 'Room',
            'visual_desc': 'Steel hold, one entrance hatch.', 'style_reference': '',
        }))

    def _saved(self):
        return json.loads(self.vfe.read_text())

    def test_critique_corrects_vocabulary_and_view(self):
        llm = FakeLLM()
        detail_room_refs('Story text.', llm, self.project)
        data = self._saved()
        self.assertEqual(data['room_vocabulary'], CLEAN_VOCAB)
        self.assertEqual(data['visual_desc'], 'Racks `server-rack-row` image-left. Empty room.')
        # The view drafts use the critiqued vocabulary, not the invented door.
        view_prompt = next(p for s, p in llm.calls if s is ROOM_DETAIL_SCHEMA)
        self.assertNotIn('side-door', view_prompt)
        # The view critic is told which ids the draft dropped.
        critique_prompt = next(p for s, p in llm.calls if s is ROOM_DETAIL_CRITIQUE_SCHEMA)
        self.assertIn('missing from the draft: server-rack-row', critique_prompt)
        self.assertIn('Steel hold, one entrance hatch.', critique_prompt)

    def test_every_room_view_declares_what_is_behind_its_camera(self):
        self.assertLessEqual({suffix for suffix, _ in _ROOM_VIEWS}, set(BEHIND_CAMERA))  # outdoor views too

    def test_view_draft_and_critique_know_what_is_behind_the_camera(self):
        self.vfe.with_name('hold-view-to-entrance.json').write_text(json.dumps({
            'name': 'Hold-View-To-Entrance', 'type': 'Room',
            'visual_desc': 'Looking back at the hatch.', 'style_reference': '',
        }))
        llm = FakeLLM()
        detail_room_refs('Story text.', llm, self.project)
        for schema in (ROOM_DETAIL_SCHEMA, ROOM_DETAIL_CRITIQUE_SCHEMA):
            prompts = [p for s, p in llm.calls if s is schema]
            self.assertTrue(any('NOT VISIBLE: the entrance wall' in p and 'VIEW: View-From-Entrance' in p
                                for p in prompts))
            self.assertTrue(any('NOT VISIBLE: the far wall' in p and 'VIEW: View-To-Entrance' in p
                                for p in prompts))

    def test_every_room_prompt_carries_door_handedness(self):
        llm = FakeLLM()
        detail_room_refs('Story text.', llm, self.project)
        self.assertEqual(len({id(s) for s, _ in llm.calls}), 4)
        for schema, prompt in llm.calls:
            self.assertIn('fixed mechanism, handedness and state', prompt, schema)

    def test_ids_with_stray_cyrillic_are_made_ascii_before_the_views_use_them(self):
        llm = FakeLLM()
        llm.make_json = lambda prompt, schema, real=llm.make_json: (
            {'issues': [], 'named_positions': [{'id': 'birbanте-Counter spot', 'description': 'd'}]}
            if schema is ROOM_VOCABULARY_CRITIQUE_SCHEMA else real(prompt, schema))
        detail_room_refs('Story text.', llm, self.project)
        self.assertEqual(self._saved()['room_vocabulary'], [{'id': 'birbante-counter-spot', 'description': 'd'}])
        self.assertIn('birbante-counter-spot', next(p for s, p in llm.calls if s is ROOM_DETAIL_SCHEMA))

    def test_failed_critic_keeps_drafts(self):
        detail_room_refs('Story text.', FakeLLM(critic_ok=False), self.project)
        data = self._saved()
        self.assertEqual(data['room_vocabulary'], DRAFT_VOCAB)
        self.assertEqual(data['visual_desc'], 'Draft without ids.')


if __name__ == '__main__':
    unittest.main()
