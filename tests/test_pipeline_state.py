"""screenplay --resume trusts pipeline_state.json only for the novel that wrote it."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.commands import screenplay
from lib.core.project import Project
from lib.core.state import ProjectState


class ResumeBindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = Project()
        self.project.output_dir = self.root / 'out'
        self.project.output_dir.mkdir()

    def _screenplay(self, text):
        novel = self.root / 'novel.txt'
        novel.write_text(text, encoding='utf-8')
        seen = []

        def master(*a, state, **kw):
            seen.append(state.episodes_done())
            state.mark_episodes_done(1)

        args = SimpleNamespace(style='s', llm='debug', novel=str(novel), resume=True, episodes_only=True)
        with mock.patch.object(screenplay, 'load_project', return_value=(self.project, {'screenplay': ''}, {})), \
                mock.patch.object(screenplay, '_make_llm'), \
                mock.patch.object(screenplay, 'load_character_refs'), \
                mock.patch.object(screenplay, 'analyze_scenes_master', side_effect=master):
            screenplay.cmd_screenplay(args)
        return seen[0]

    def test_resume_keeps_progress_for_the_same_novel(self):
        self._screenplay('Глава 1')
        self.assertTrue(self._screenplay('Глава 1'))

    def test_another_novel_starts_from_scratch(self):
        self._screenplay('Глава 1')
        self.assertFalse(self._screenplay('Глава 2'))

    def test_a_legacy_state_without_a_source_is_adopted(self):
        legacy = ProjectState.load(self.project.state_path())
        legacy.mark_episodes_done(1)
        self.assertTrue(self._screenplay('Глава 1'))
        self.assertFalse(self._screenplay('Глава 2'))


if __name__ == '__main__':
    unittest.main()
