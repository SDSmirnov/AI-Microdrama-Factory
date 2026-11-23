"""Recommended make chain: stage order and the guards that keep room views QA-gated."""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.commands import setup, storyboard
from lib.core.project import Project
from lib.studio import artist, director
from lib.studio.artist import ref_render

ROOT = Path(__file__).resolve().parents[1]


class _RefDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ref_dir = Path(tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir

    def write(self, name, type_, **extra):
        data = {'name': name, 'type': type_, 'visual_desc': 'Desc.', 'style_reference': '', **extra}
        path = self.ref_dir / f'{name.lower()}.json'
        path.write_text(json.dumps(data))
        return path


class RefsFilterTests(_RefDir):
    def setUp(self):
        super().setUp()
        self.write('Hold-View-From-Left-Wall', 'Room')
        self.write('Beach-View-Primary', 'Outdoor')
        self.write('Lin', 'Character')

    def _rendered(self, **kwargs):
        names = []
        with mock.patch.object(ref_render, '_render_single_ref',
                               side_effect=lambda c, *a, **k: names.append(c['name'])):
            artist.render_character_refs({}, {}, None, self.project, **kwargs)
        return sorted(names)

    def test_no_rooms_leaves_room_and_outdoor_views_to_room_views(self):
        self.assertEqual(self._rendered(no_rooms=True), ['Lin'])

    def test_types_filter(self):
        self.assertEqual(self._rendered(types={'Outdoor'}), ['Beach-View-Primary'])


class ContinuityRoomGuardTests(_RefDir):
    def test_room_views_are_not_enriched_or_rerendered(self):
        path = self.write('Hold-View-From-Left-Wall', 'Room')
        before = path.read_text()
        llm = mock.Mock()
        director.enrich_and_regenerate_reference(
            'Hold-View-From-Left-Wall', ['panel usage'], llm, self.ref_dir, dry_run=False
        )
        self.assertFalse(llm.method_calls)
        self.assertEqual(path.read_text(), before)


class RoomViewsExitTests(unittest.TestCase):
    def _run(self, summary, **flags):
        args = SimpleNamespace(style='s', llm='debug', rooms='', pass_threshold=9,
                               max_attempts=1, edit_attempts=1, **flags)
        with mock.patch.object(setup, 'load_project', return_value=(Project(), {'screenplay': ''}, {})), \
                mock.patch.object(setup, '_make_vision_llm'), \
                mock.patch.object(setup, 'run_room_views', return_value=summary) as run_views:
            setup.cmd_room_views(args)
        return run_views

    def test_blocked_room_stops_the_chain(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run({'rooms': {'Hold': {'error': 'VFE QA failed'}}, 'failed_vte': []})
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(SystemExit):
            self._run({'rooms': {'Hold': {}}, 'failed_vte': ['Hold']})

    def test_waived_vte_and_clean_runs_pass(self):
        run = self._run({'rooms': {'Hold': {}}, 'failed_vte': ['Hold']},
                        allow_unverified_vte=True)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(run.call_args.kwargs['allow_unverified_vte'])
        run = self._run({'rooms': {'Hold': {}}, 'passed_vte': ['Hold'],
                         'failed_vte': []})
        self.assertEqual(run.call_count, 1)
        self.assertFalse(run.call_args.kwargs['allow_unverified_vte'])


class PanelByPanelCliTests(unittest.TestCase):
    def test_accepts_all_and_resume(self):
        parser = argparse.ArgumentParser()
        storyboard.register(parser.add_subparsers())
        args = parser.parse_args(['panel-by-panel-with-qa', 'all', '--skip-existing'])
        self.assertEqual(args.scene, 'all')
        self.assertTrue(args.skip_existing)
        self.assertEqual(args.max_attempts, 3)


class MakefileProductionTests(unittest.TestCase):
    def test_production_stage_order(self):
        makefile = (ROOT / 'Makefile').read_text()
        body = makefile.split('\nproduction:', 1)[1].split('\n\n', 1)[0]
        stages = [line.strip() for line in body.splitlines() if '$(MAKE)' in line]
        expected = [
            'init', 'styles', 'bible', 'casting', 'detail-rooms', 'room-plan', 'room-views',
            'screenplay RESUME=1', 'consistency DRY_RUN=1',
            'refs NO_ROOMS=1', 'disposition SCENE=all', 'spatial-rewrite SCENE=all',
            'panel-by-panel-with-qa SCENE=all SKIP_EXISTING=1',
        ]
        self.assertEqual([s.split('$(MAKE) ', 1)[1] for s in stages], expected)
        # styles overwrites custom_prompts/: guarded to fresh projects only.
        self.assertIn('[ -f custom_prompts/style.md ] || $(MAKE) styles', body)
        # bible reads the whole book: skipped when there are no chapter files.
        self.assertIn('[ -z "$(CHAPTERS)" ] || $(MAKE) bible', body)

    def test_room_qa_threshold_is_not_the_panel_threshold(self):
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('extra-room-refs-qa --threshold $(ROOM_THRESHOLD)', makefile)
        self.assertIn('ROOM_THRESHOLD ?= 9', makefile)


if __name__ == '__main__':
    unittest.main()
