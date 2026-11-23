import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.screenwriter import spatial as sw

ANCHORS = {'zones': [{'label': 'sofa', 'x': 0.2, 'y': 0.7}, {'label': 'bar counter', 'x': 0.8, 'y': 0.3}]}


def _scene():
    return {'scene_id': 1, 'location': 'Bar', 'panels': [
        {'panel_index': 1, 'references': ['Alisa'], 'location_references': ['Bar-View-From-Entrance'],
         'visual_start': 'Alisa on the frame-left'},
        {'panel_index': 2, 'references': ['Pavel'], 'location_references': ['Bar-View-From-Entrance'],
         'visual_start': 'Pavel on the frame-right'},
    ]}


class _LLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def make_json(self, prompt, schema):
        self.prompts.append(prompt)
        return copy.deepcopy(self.reply)


SWAP_P1 = [{'panel_index': 1, 'visual_disposition': 'Alisa on the sofa', 'swap_view': True},
           {'panel_index': 2, 'visual_disposition': 'Pavel by the bar counter', 'swap_view': False}]


class DispositionPassTests(unittest.TestCase):
    def _run(self, reply, anchors=ANCHORS, **kw):
        llm = _LLM(reply)
        scene = sw.apply_spatial_disposition_pass(_scene(), anchors, llm, **kw)
        return scene['panels'], llm.prompts

    def test_swap_flips_view_and_mirrors_frame_directions(self):
        (p1, p2), _ = self._run(SWAP_P1, anchors={})
        self.assertEqual(p1['location_references'], ['Bar-View-To-Entrance'])
        self.assertEqual(p1['visual_start'], 'Alisa on the frame-right')
        self.assertEqual(p1['visual_disposition'], 'Alisa on the sofa')
        self.assertEqual(p2['location_references'], ['Bar-View-From-Entrance'])
        self.assertEqual(p2['visual_start'], 'Pavel on the frame-right')

    def test_swap_to_unknown_ref_is_skipped(self):
        (p1, _), _ = self._run(SWAP_P1, anchors={}, available_refs=frozenset({'Bar-View-From-Entrance'}))
        self.assertEqual(p1['location_references'], ['Bar-View-From-Entrance'])
        self.assertEqual(p1['visual_start'], 'Alisa on the frame-left')

    def test_backend_that_gave_up_is_not_called_again(self):
        llm = mock.Mock(**{'make_json.side_effect': RuntimeError('503 Service Unavailable')})
        with mock.patch('time.sleep'), self.assertRaises(RuntimeError):
            sw.apply_spatial_disposition_pass(_scene(), ANCHORS, llm)
        llm.make_json.assert_called_once()

    def test_empty_reply_leaves_panels_untouched(self):
        panels, _ = self._run([])
        self.assertEqual(panels, _scene()['panels'])

    def test_prompt_carries_rules_and_optional_continuity(self):
        _, (plain,) = self._run([], anchors={})
        _, (cont,) = self._run([], anchors={}, prev_terminal_disposition='Alisa on the sofa')
        self.assertIn(sw._DISPOSITION_RULES, plain)
        self.assertNotIn('CROSS-SCENE ANCHOR CONTINUITY', plain)
        self.assertIn('CROSS-SCENE ANCHOR CONTINUITY', cont)

    def test_puppet_rewrites_disposition_from_zones(self):
        (p1, _), _ = self._run(SWAP_P1)
        self.assertNotEqual(p1['visual_disposition'], 'Alisa on the sofa')
        self.assertIn('Alisa', p1['visual_disposition'])

    def test_puppet_failure_keeps_llm_disposition(self):
        with mock.patch.object(sw._puppet, 'build_scene_frames', side_effect=RuntimeError):
            (p1, _), _ = self._run(SWAP_P1)
        self.assertEqual(p1['visual_disposition'], 'Alisa on the sofa')


if __name__ == '__main__':
    unittest.main()
