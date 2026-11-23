"""Actor-line rendering: present fields become clauses, missing ones are dropped."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.prompts import actor_line, get_default_config
from lib.studio.artist.grids import _build_grid_prompt


class ActorLineTests(unittest.TestCase):
    def test_full_actor(self):
        a = {'pose': 'standing', 'position': 'by the door', 'gaze_target': 'Oli',
             'chest_direction': 'toward the window', 'head_direction': 'toward Oli'}
        self.assertEqual(actor_line(a, 'Cal'), (
            'Cal: standing by the door, looking at Oli, body facing toward the window, '
            'head facing toward Oli.'))

    def test_missing_fields_drop_clauses(self):
        self.assertEqual(actor_line({'pose': 'sitting', 'gaze_target': None}, 'Cal'),
                         'Cal: sitting.')


class GridPromptTests(unittest.TestCase):
    def test_grid_prompt_without_head_direction(self):
        actor = {'name': 'Cal', 'pose': 'sitting', 'position': 'left', 'gaze_target': 'Oli',
                 'chest_direction': 'toward Oli', 'in_frame': True}
        scene = {'scene_id': 1, 'location': 'Yard', 'panels': [
            {'panel_index': i, 'state': {'actors': [actor]}} for i in range(1, 5)]}
        self.assertIn('Cal: sitting left', _build_grid_prompt(scene, {}, get_default_config()))


if __name__ == '__main__':
    unittest.main()
