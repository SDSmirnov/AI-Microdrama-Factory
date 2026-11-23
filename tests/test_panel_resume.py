"""panel-by-panel-with-qa: resume by QA record, never refine an unjudged panel."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.commands import storyboard
from lib.core.project import Project


def _png(color):
    buf = io.BytesIO()
    Image.new('RGB', (16, 9), color).save(buf, format='PNG')
    return buf.getvalue()


class PanelResumeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.project = Project()
        self.project.panels_dir = root / 'panels'
        self.project.refined_dir = root / 'refined'
        self.project.ref_dir = root / 'refs'
        for d in (self.project.panels_dir, self.project.refined_dir, self.project.ref_dir):
            d.mkdir()
        self.png = self.project.panels_dir / '001_01_static.png'
        self.scene = {'scene_id': 1, 'panels': [{'panel_index': 1}]}

    def _run(self, verdicts, skip_existing=False, refine=False):
        renders, judged = [], []

        def refined(*args, **kwargs):
            (self.project.refined_dir / '001_01_static_refined.png').write_bytes(_png((0, 9, 0)))
            return True

        def render(*args, **kwargs):
            renders.append(1)
            self.png.write_bytes(_png((len(renders), 0, 0)))

        def judge(**kwargs):
            judged.append(1)
            return verdicts.pop(0)

        args = SimpleNamespace(max_attempts=2, threshold=5, skip_existing=skip_existing)
        with mock.patch.object(storyboard, '_render_single_panel', side_effect=render), \
                mock.patch.object(storyboard, 'analyze_panel', side_effect=judge), \
                mock.patch.object(storyboard, 'load_ref_catalog', return_value={}), \
                mock.patch.object(storyboard, 'refine_panel', side_effect=refined if refine else None,
                                  return_value=False) as refine:
            failed = storyboard._panel_by_panel_scene(
                self.scene, {'scenes': [self.scene]}, None, args, self.project, {},
                {'image_generation': {}}, None, None)
        return failed, len(renders), len(judged), refine.call_count

    def test_resume_skips_passed_panels_and_rejudges_unpassed_ones(self):
        self.assertEqual(self._run([{'needs_refinement': False, 'fidelity': 9}]), (0, 1, 1, 0))
        # Passed and unchanged: no render, no QA.
        self.assertEqual(self._run([], skip_existing=True), (0, 0, 0, 0))
        # Image changed since it passed: QA again, but do not re-render.
        self.png.write_bytes(_png((9, 9, 9)))
        self.assertEqual(self._run([{'needs_refinement': False, 'fidelity': 9}],
                                   skip_existing=True), (0, 0, 1, 0))

    def test_without_skip_existing_an_existing_panel_is_rendered_again(self):
        self.png.write_bytes(_png((9, 9, 9)))
        self.assertEqual(self._run([{'needs_refinement': False, 'fidelity': 9}]), (0, 1, 1, 0))

    def test_judge_failure_is_never_refined_and_counts_as_failed(self):
        failed, renders, judged, refines = self._run(
            [{'needs_refinement': True, 'api_error': True, 'fidelity': 0}])
        self.assertEqual((failed, renders, judged, refines), (1, 1, 1, 0))
        self.assertTrue(storyboard._panel_qa_path(self.png).exists())
        self.assertFalse(storyboard._panel_qa_passed(self.png))

    def test_an_accepted_refinement_is_judged_once(self):
        failed, _, judged, refines = self._run(
            [{'needs_refinement': True, 'fidelity': 5}, {'needs_refinement': False, 'fidelity': 9}],
            refine=True)
        self.assertEqual((failed, judged, refines), (0, 2, 1))
        self.assertEqual(self.png.read_bytes(), _png((0, 9, 0)))

    def test_a_rejected_refinement_does_not_rejudge_the_unchanged_original(self):
        failed, _, judged, refines = self._run(
            [{'needs_refinement': True, 'fidelity': 6},
             {'needs_refinement': True, 'fidelity': 6, 'critical_artifacts': ['[CRITICAL] extra rifle']}],
            refine=True)
        self.assertEqual((failed, judged, refines), (1, 2, 1))
        self.assertEqual(self.png.read_bytes(), _png((1, 0, 0)))


if __name__ == '__main__':
    unittest.main()
