"""panel_lint flags HARD-FAILURE rule violations in Pass 2/3 output; the scene pipeline retries that pass once."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import panel_lint
from lib.studio.screenwriter.enforce import _enforce_lint


def p2(*panels):
    return {'panels': [{'panel_index': i, 'visual_start': vs, 'visual_end': ve} for i, (vs, ve) in enumerate(panels, 1)]}


class VisualIssueTests(unittest.TestCase):
    def test_flowing_tears_and_sweat_fail(self):
        issues = panel_lint.visual_issues(p2(('ANNA: frame-LEFT MG, tears stream down cheeks', 'brow sweating')), None, 1)
        self.assertEqual(len(issues), 2)

    def test_allowed_wording_passes(self):
        ok = p2(('ANNA: one tear traces cheekbone, grey sweater', 'MAX tears the envelope open'))
        self.assertEqual(panel_lint.visual_issues(ok, None, 1), [])

    def test_actor_line_for_out_of_frame_actor_fails(self):
        p1a = {'panels': [{'panel_index': 1, 'state': {'actors': [{'name': 'Max', 'in_frame': False},
                                                                  {'name': 'Anna', 'in_frame': True}]}}]}
        issues = panel_lint.visual_issues(p2(('Anna: frame-LEFT\nMax: frame-RIGHT BG', 'Anna: frame-LEFT')), p1a, 1)
        self.assertEqual([(i.character, i.panel_index) for i in issues], [('Max', 1)])


class MotionIssueTests(unittest.TestCase):
    def test_camera_direction_and_voice_budget(self):
        p3 = {'panels': [
            {'panel_index': 1, 'motion_prompt': '0s Anna steps toward the camera 2 steps', 'duration': 2,
             'dialogue': 'Anna (F): ' + 'x' * 40, 'voiceover': 'y' * 10},
            {'panel_index': 2, 'motion_prompt': '0s Anna steps toward [door], 2 steps', 'duration': 2,
             'dialogue': 'Anna (F): ' + 'x' * 40, 'voiceover': ''}]}
        messages = [str(i) for i in panel_lint.motion_issues(p3, 3)]
        self.assertEqual(len(messages), 2)
        self.assertIn('toward the camera', messages[0])
        self.assertIn('50 chars', messages[1])

    def test_voiceover_colon_is_not_a_speaker_prefix(self):
        p3 = {'panels': [{'panel_index': 1, 'motion_prompt': '', 'duration': 1, 'dialogue': '',
                          'voiceover': 'Wait: ' + 'z' * 20}]}
        self.assertEqual(len(panel_lint.motion_issues(p3, 1)), 1)


class EnforceLintTests(unittest.TestCase):
    BAD, GOOD = p2(('tears stream', '')), p2(('jaw clenches 2 mm', ''))

    def lint(self, r):
        return panel_lint.visual_issues(r, None, 1)

    def test_retry_with_fewer_issues_wins_and_gets_the_issue_list(self):
        seen = []
        out = _enforce_lint(self.BAD, lambda c: seen.append(c) or self.GOOD, self.lint, 'Pass 2')
        self.assertIs(out, self.GOOD)
        self.assertIn('tears stream', seen[0])

    def test_no_retry_when_clean_and_first_kept_when_retry_is_no_better(self):
        self.assertIs(_enforce_lint(self.GOOD, lambda c: self.fail('retried'), self.lint, 'Pass 2'), self.GOOD)
        self.assertIs(_enforce_lint(self.BAD, lambda c: self.BAD, self.lint, 'Pass 2'), self.BAD)


if __name__ == '__main__':
    unittest.main()
