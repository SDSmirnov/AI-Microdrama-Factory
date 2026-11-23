"""Style presets inherit through config.json `extends`; `name.patch.md` edits the inherited prompt."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core import prompts as prompts_mod
from lib.core.utils import grid_dims
from lib.studio.screenwriter.episodes import _clamp_panel_counts, _episode_type_block

REPO_PROMPTING = prompts_mod.PROMPTING_DIR
SHIPPED_STYLES = sorted(d.name for d in REPO_PROMPTING.iterdir() if d.is_dir())
PASS_PROMPTS = ('pass1_architecture', 'pass1a_state', 'pass1b_disposition', 'pass2_visual', 'pass3_motion_audio')
LATE_BOUND = {'{{PANEL_DURATION}}'}   # filled by screenwriter._episode_type_block

LANDSCAPE_COUNTS = [4, 9, 12]
BASE = "# Title\n\n## A\na-body\n\n---\n\n## B\nb-body\n### B1\nb1-body\n## C\nc-body\n"


class _TempStyles(unittest.TestCase):
    """Style dirs in a temp PROMPTING_DIR; no custom_prompts/ overlay."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [mock.patch.object(prompts_mod, 'PROMPTING_DIR', root / 'prompting'),
                   mock.patch.object(prompts_mod, 'CUSTOM_PROMPTS_DIR', root / 'custom_prompts')]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def style(self, name: str, config: dict = None, **files: str) -> None:
        d = prompts_mod.PROMPTING_DIR / name
        d.mkdir(parents=True)
        if config is not None:
            (d / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        for stem, text in files.items():
            (d / f"{stem.replace('__patch', '.patch')}.md").write_text(text, encoding='utf-8')


class PatchTests(unittest.TestCase):
    def test_replace_touches_only_its_section(self):
        out = prompts_mod.apply_patch(BASE, "<!-- replace: ## A -->\n## A2\nnew\n")
        self.assertEqual(out, BASE.replace("## A\na-body\n\n---\n", "## A2\nnew\n"))

    def test_level2_replace_takes_its_subsections_level3_does_not(self):
        out = prompts_mod.apply_patch(BASE, "<!-- replace: ## B -->\n## B\nx\n")
        self.assertNotIn("b1-body", out)
        self.assertIn("## C\nc-body", out)
        out = prompts_mod.apply_patch(BASE, "<!-- replace: ### B1 -->\n### B1\nx\n")
        self.assertIn("## B\nb-body", out)
        self.assertNotIn("b1-body", out)
        self.assertIn("## C\nc-body", out)

    def test_empty_replace_deletes_the_section(self):
        out = prompts_mod.apply_patch(BASE, "<!-- replace: ## B -->\n")
        self.assertNotIn("## B", out)
        self.assertIn("## A\na-body", out)
        self.assertIn("## C\nc-body", out)

    def test_append_adds_at_the_end(self):
        out = prompts_mod.apply_patch(BASE, "<!-- append -->\n## D\nd-body\n")
        self.assertEqual(out, BASE + "\n## D\nd-body\n")

    def test_replacement_text_is_literal(self):
        out = prompts_mod.apply_patch(BASE, "<!-- replace: ## A -->\n## A\nregex \\1 and \\g<0>\n")
        self.assertIn("regex \\1 and \\g<0>", out)

    def test_unknown_or_ambiguous_heading_raises(self):
        with self.assertRaisesRegex(ValueError, "matches 0 sections"):
            prompts_mod.apply_patch(BASE, "<!-- replace: ## Renamed -->\nx\n")
        with self.assertRaisesRegex(ValueError, "matches 2 sections"):
            prompts_mod.apply_patch(BASE + "## A\nagain\n", "<!-- replace: ## A -->\nx\n")

    def test_text_outside_directives_raises(self):
        for patch in ("stray\n<!-- append -->\nx\n", "\n", "<!-- replace: not a heading -->\nx\n"):
            with self.assertRaisesRegex(ValueError, "expected only replace/append"):
                prompts_mod.apply_patch(BASE, patch)


class ChainTests(_TempStyles):
    def test_child_file_wins_and_unlisted_files_are_inherited(self):
        self.style('base', {}, style="base style", casting="base casting")
        self.style('child', {'extends': 'base'}, style="child style")
        loaded, _ = prompts_mod.load_prompts('child')
        self.assertEqual(loaded['style'], "child style")
        self.assertEqual(loaded['casting'], "base casting")

    def test_patches_apply_in_chain_order(self):
        self.style('base', {}, qa=BASE)
        self.style('mid', {'extends': 'base'}, qa__patch="<!-- replace: ## A -->\n## A-mid\nmid\n")
        self.style('leaf', {'extends': 'mid'}, qa__patch="<!-- replace: ## A-mid -->\n## A-leaf\nleaf\n")
        self.assertIn("## A-leaf\nleaf", prompts_mod.load_prompts('leaf')[0]['qa'])
        self.assertIn("## A-mid\nmid", prompts_mod.load_prompts('mid')[0]['qa'])

    def test_placeholders_in_patch_text_are_substituted(self):
        self.style('base', {}, qa=BASE)
        self.style('child', {'extends': 'base'}, qa__patch="<!-- append -->\n## D\nmax {{VIDEO_MAX_SECONDS}} s\n")
        self.assertNotIn("{{VIDEO_MAX_SECONDS}}", prompts_mod.load_prompts('child')[0]['qa'])

    def test_config_deep_merges_and_drops_extends(self):
        self.style('base', {'format': {'a': 1, 'b': 2}, 'keep': True})
        self.style('child', {'extends': 'base', 'format': {'b': 3}})
        _, config = prompts_mod.load_prompts('child')
        self.assertEqual(config['format'], {'a': 1, 'b': 3})
        self.assertTrue(config['keep'])
        self.assertNotIn('extends', config)

    def test_cycle_raises(self):
        self.style('a', {'extends': 'b'})
        self.style('b', {'extends': 'a'})
        with self.assertRaisesRegex(ValueError, "missing or cyclic"):
            prompts_mod.load_prompts('a')

    def test_missing_parent_raises_instead_of_falling_back(self):
        self.style('child', {'extends': 'nope'})
        with self.assertRaisesRegex(ValueError, "missing or cyclic"):
            prompts_mod.load_prompts('child')

    def test_full_file_and_patch_together_raise(self):
        self.style('base', {}, qa=BASE)
        self.style('child', {'extends': 'base'}, qa="x", qa__patch="<!-- append -->\ny\n")
        with self.assertRaisesRegex(ValueError, "needs an inherited"):
            prompts_mod.load_prompts('child')

    def test_patch_without_inherited_file_raises(self):
        self.style('base', {})
        self.style('child', {'extends': 'base'}, qa__patch="<!-- append -->\ny\n")
        with self.assertRaisesRegex(ValueError, "needs an inherited"):
            prompts_mod.load_prompts('child')

    def test_episode_type_files_are_discovered_through_the_chain(self):
        self.style('base', {}, episode_type_heist="base heist")
        self.style('child', {'extends': 'base'}, episode_type_chase="child chase")
        loaded, config = prompts_mod.load_prompts('child')
        self.assertEqual(_episode_type_block('heist', '', loaded, config), "base heist")
        self.assertEqual(_episode_type_block('chase', '', loaded, config), "child chase")
        self.assertEqual(_episode_type_block('standard', '', loaded, config), "")


class _ShippedStyles(unittest.TestCase):
    """The real lib/prompting/, without the working directory's custom_prompts/ overlay."""

    def setUp(self):
        p = mock.patch.object(prompts_mod, 'CUSTOM_PROMPTS_DIR', Path(tempfile.gettempdir()) / 'no-such-custom-prompts')
        p.start()
        self.addCleanup(p.stop)


class ShippedPresetTests(_ShippedStyles):
    def resolved(self, style: str) -> dict:
        loaded, _ = prompts_mod.load_prompts(style)
        loaded['book-shrinker'] = prompts_mod.resolve_style_file(style, 'book-shrinker') or ''
        return loaded

    def test_every_style_resolves_with_all_pass_prompts(self):
        for style in SHIPPED_STYLES:
            loaded = self.resolved(style)
            for name in PASS_PROMPTS + ('screenplay', 'screenplay_episodes', 'qa', 'casting', 'imagery', 'book-shrinker'):
                self.assertTrue(loaded[name].strip(), f"{style}: {name} resolved empty")

    def test_no_loader_placeholder_survives(self):
        for style in SHIPPED_STYLES:
            for name, text in self.resolved(style).items():
                left = set(re.findall(r'\{\{[A-Z_]+\}\}', text)) - LATE_BOUND
                self.assertEqual(left, set(), f"{style}/{name}")

    def test_action_drops_drama_framing_and_keeps_inherited_rules(self):
        loaded = self.resolved('action_movie_9_16')
        text = "\n".join(loaded.values())
        for phrase in ("faces dominate", "Faces and close-ups are the primary dramatic instrument", "__MULTI_POV_INSTRUCTION__"):
            self.assertNotIn(phrase, text)
        self.assertIn("View-From-Left-Wall", loaded['pass2_visual'])          # inherited location naming
        self.assertIn("FALLEN/INCAPACITATED CHARACTER", loaded['pass3_motion_audio'])   # inherited moderation rule
        self.assertIn("APPENDIX D", loaded['motion_dynamics'])
        self.assertIn("WEAPON AND PROP STATE", loaded['pass2_visual'])

    def test_action_episode_types_reach_the_scene_generator(self):
        loaded, config = prompts_mod.load_prompts('action_movie_9_16')
        for episode_type in ('action', 'chase', 'dialogue', 'reveal', 'transition'):
            self.assertTrue(_episode_type_block(episode_type, '', loaded, config).strip(), episode_type)
            self.assertIn(f"`{episode_type}`", loaded['screenplay_episodes'])

    def test_action_prohibitions_allow_exertion(self):
        from lib.animation.base import ANIMATION_PROHIBITIONS
        from lib.animation.prompt_builder import _hard_prohibitions
        loaded, _ = prompts_mod.load_prompts('action_movie_9_16')
        self.assertNotIn("NO sweat", _hard_prohibitions(loaded))
        self.assertIn("NO tears", _hard_prohibitions(loaded))
        generic, _ = prompts_mod.load_prompts('vertical_9_16_generic')
        self.assertEqual(_hard_prohibitions(generic), ANIMATION_PROHIBITIONS)

    def test_wide_has_no_vertical_format_rules(self):
        loaded = self.resolved('action_movie_16_9_wide')
        banned = ("9:16", "PORTRAIT FRAME", "Top 15% and bottom 20%", "MUTED VIEWING", "muted viewers",
                  "faces dominate", "Emphasize Verticality", "VERTICAL CINEMATIC", "subtitles/UI")
        for name, text in loaded.items():
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{name} still carries {phrase!r}")
        for name in ('style', 'screenplay', 'pass2_visual', 'casting', 'imagery', 'qa'):
            self.assertIn("16:9", loaded[name], name)
        self.assertIn("WEAPON AND PROP STATE", loaded['pass2_visual'])        # action layer survives under the wide one

    def test_wide_config(self):
        _, config = prompts_mod.load_prompts('action_movie_16_9_wide')
        self.assertEqual(config['format']['panel_aspect_ratio'], '16:9')
        self.assertEqual(config['image_generation']['aspect_ratio'], '16:9')
        self.assertEqual(config['format']['panel_count_options'], LANDSCAPE_COUNTS)

    def test_new_styles_are_registered_for_the_styles_command(self):
        from lib.studio.stylist import STYLE_PRESETS, _normalize_style_key
        for style in ('action_movie_9_16', 'action_movie_16_9_wide'):
            self.assertEqual(_normalize_style_key(style), style)
            _, config = prompts_mod.load_prompts(style)
            self.assertEqual(STYLE_PRESETS[style]['aspect_ratio'], config['image_generation']['aspect_ratio'])
            self.assertEqual(STYLE_PRESETS[style]['panel_count_options'], config['format']['panel_count_options'])


class LandscapeGridTests(unittest.TestCase):
    def test_landscape_layouts(self):
        self.assertEqual(grid_dims(4, '16:9'), (2, 2, '16:9'))
        self.assertEqual(grid_dims(9, '16:9'), (3, 3, '16:9'))
        self.assertEqual(grid_dims(12, '16:9'), (3, 4, '4:3'))

    def test_grid_aspect_matches_cells(self):
        for count in LANDSCAPE_COUNTS:
            cols, rows, grid_ar = grid_dims(count, '16:9')
            w, h = (int(x) for x in grid_ar.split(':'))
            self.assertEqual(cols * 16 * h, rows * 9 * w, f"{count} panels: {grid_ar} is not {cols}x{rows} cells of 16:9")

    def test_portrait_layouts_unchanged(self):
        self.assertEqual(grid_dims(12), (4, 3, '3:4'))
        self.assertEqual(grid_dims(12, '9:16'), grid_dims(12))

    def test_counts_without_a_landscape_layout_raise(self):
        for count in (6, 10):
            with self.assertRaises(ValueError):
                grid_dims(count, '16:9')

    def test_panel_counts_snap_to_allowed_options(self):
        screenplay = {'episodes': [{'episode_id': 1, 'scenes': [
            {'scene_local_id': 1, 'panel_count': 6}, {'scene_local_id': 2, 'panel_count': 10},
            {'scene_local_id': 3, 'panel_count': 9}, {'scene_local_id': 4}]}]}
        with self.assertLogs('lib.studio.screenwriter', level='WARNING') as logs:
            scenes = _clamp_panel_counts(screenplay, [4, 9, 12])['episodes'][0]['scenes']
        self.assertEqual([s.get('panel_count') for s in scenes], [4, 9, 9, None])
        self.assertEqual(len(logs.output), 2)


class FormatWordingTests(_ShippedStyles):
    def _scene(self):
        return {'scene_id': 1, 'location': 'Depot', 'panels': [
            {'panel_index': i, 'visual_start': 'x', 'state': {'actors': []}} for i in range(1, 5)]}

    def test_exported_grid_prompt_follows_config(self):
        from lib.studio.artist import _build_image_prompt
        for style, present, absent in (
                ('vertical_9_16_generic', ("Top 15% and bottom 20%", "vertical microdrama"), ()),
                ('action_movie_9_16', ("Top 15% and bottom 20%", "Action geography"), ("vertical microdrama",)),
                ('action_movie_16_9_wide', ("HORIZONTAL frame", "Widescreen action cinema"), ("SAFE ZONE", "vertical microdrama"))):
            loaded, config = prompts_mod.load_prompts(style)
            text = _build_image_prompt(self._scene(), loaded, config)
            for phrase in present:
                self.assertIn(phrase, text, style)
            for phrase in absent:
                self.assertNotIn(phrase, text, style)

    def test_single_panel_prompt_names_the_orientation(self):
        from lib.studio.artist import _build_panel_prompt
        panel = self._scene()['panels'][0]
        wide = _build_panel_prompt(self._scene(), panel, 'static', {}, '16:9')
        tall = _build_panel_prompt(self._scene(), panel, 'static', {}, '9:16')
        self.assertIn("SINGLE landscape image (16:9)", wide)
        self.assertNotIn("portrait", wide.lower())
        self.assertIn("SINGLE portrait image (9:16)", tall)

    def test_video_aspect_follows_style_unless_env_overrides(self):
        from lib.commands.animation import _video_aspect
        _, config = prompts_mod.load_prompts('action_movie_16_9_wide')
        with mock.patch.dict('os.environ', {}, clear=False) as env:
            env.pop('AI_VIDEO_ASPECT', None)
            self.assertEqual(_video_aspect(config), '16:9')
            env['AI_VIDEO_ASPECT'] = '1:1'
            self.assertEqual(_video_aspect(config), '1:1')


if __name__ == '__main__':
    unittest.main()
