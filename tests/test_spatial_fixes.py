"""Spatial and reference fixes from the 2026-11-13 pipeline review.

Each test pins one defect found by reading the code:
  - _render_single_panel / render_extra_panel read an undefined `config`, so
    every per-panel render died in a swallowed NameError;
  - the screenwriter's side-wall left/right table was the mirror image of the
    renderer's projection (artist._project_image_x);
  - the panel anchor block was projected from the view's wall camera, not the
    panel's own camera;
  - every scene received every location's refs;
  - a character variation got its parent face labelled as a style hint.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core import puppet
from lib.core.project import Project
from lib.core.prompts import resolve_style_file
from lib.studio import artist
from lib.studio.screenwriter import episodes, passes

ANCHORS = {
    'room_m': [4.0, 6.0],
    'objects': [
        # id ≠ label, as the anchor pass really writes them (CRAB: 'watertight-hatch' / 'Heavy watertight hatch (open)')
        {'id': 'entrance-door', 'label': 'Steel entrance door', 'x': 0.5, 'y': 0.0, 'z': 0.5, 'width_x': 0.2, 'depth_y': 0.0},
        {'id': 'sofa', 'label': 'Grey corner sofa', 'x': 0.2, 'y': 0.5, 'z': 0.2, 'width_x': 0.3, 'depth_y': 0.2},
        {'id': 'window', 'label': 'Panoramic window', 'x': 0.8, 'y': 1.0, 'z': 0.5, 'width_x': 0.3, 'depth_y': 0.0},
    ],
}


def _tmpdir(case):
    path = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


class _FakeImageLLM:
    def __init__(self):
        self.calls = []

    def make_image(self, prompt, refs=None, aspect_ratio=None, image_size=None):
        self.calls.append({'prompt': prompt, 'refs': refs, 'image_size': image_size})
        return b'png-bytes'


def _panel():
    return {'panel_index': 1, 'visual_start': 'MS 50mm eye-level cam@entrance-door',
            'references': [], 'location_references': [], 'state': {'actors': []}}


class PanelRenderConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir(self)
        self.project = Project(output_dir=self.tmp, ref_dir=self.tmp / 'refs', panels_dir=self.tmp / 'panels')
        self.project.ensure_dirs()
        self.llm = _FakeImageLLM()
        self.config = {'image_generation': {'image_size': '4K'}}

    def test_single_panel_is_written_at_configured_size(self):
        artist._render_single_panel({'location': 'Office'}, _panel(), 1, 'static', '9:16',
                                    self.project, self.llm, {}, self.config)
        self.assertTrue((self.project.panels_dir / '001_01_static.png').exists())
        self.assertEqual(self.llm.calls[0]['image_size'], '4K')

    def test_extra_panel_is_written_at_configured_size(self):
        out = self.tmp / 'extra' / '001_4_5_static.png'
        artist.render_extra_panel({'location': 'Office'}, _panel(), out, '9:16',
                                  self.project, self.llm, {}, self.config)
        self.assertTrue(out.exists())
        self.assertEqual(self.llm.calls[0]['image_size'], '4K')


class RenderFailuresAreReported(unittest.TestCase):
    def test_crashed_task_is_logged_and_others_finish(self):
        done = []

        def render(task):
            if task == 2:
                raise KeyError('pose')
            done.append(task)

        with self.assertLogs('lib.studio.artist', level='ERROR') as logs:
            artist._run_render_tasks(render, [1, 2, 3], lambda t: f'panel {t}', workers=2)
        self.assertEqual(sorted(done), [1, 3])
        self.assertTrue(any('Render crashed for panel 2' in m for m in logs.output))
        self.assertTrue(any('1/3 render task(s) crashed' in m for m in logs.output))

    def test_actor_with_missing_fields_still_builds_a_prompt(self):
        panel = {'panel_index': 1, 'visual_start': 'MS', 'state': {'actors': [
            {'name': 'Anna', 'in_frame': True, 'pose': 'standing', 'gaze_target': None},
            {'name': 'Mike'},
        ]}}
        prompt = artist._build_panel_prompt({'location': 'Office'}, panel, 'static', {})
        self.assertIn('Actors: Anna: standing.', prompt)
        self.assertNotIn('None', prompt)
        self.assertNotIn('Mike', prompt)

    def test_panel_prompt_forbids_printing_reference_ids(self):
        prompt = artist._build_panel_prompt({'location': 'Office'}, {'panel_index': 1}, 'static', {})
        self.assertIn('never print them', prompt)


class SideWallMirror(unittest.TestCase):
    """Entrance-side objects (low y) are image-RIGHT from the left wall, image-LEFT from the right wall."""

    def test_renderer_projection(self):
        self.assertGreater(artist._project_image_x(0.5, 0.1, 'View-From-Left-Wall'), 0.5)
        self.assertLess(artist._project_image_x(0.5, 0.1, 'View-From-Right-Wall'), 0.5)

    def test_screenwriter_table_agrees_with_renderer(self):
        left = passes._axis_for_panel(['Office-View-From-Left-Wall'])
        right = passes._axis_for_panel(['Office-View-From-Right-Wall'])
        self.assertIn('y>0.65→frame-left', left)
        self.assertIn('y<0.35→frame-right', left)
        self.assertIn('y<0.35→frame-left', right)
        self.assertIn('y>0.65→frame-right', right)

    def test_pass2_prompts_agree_with_renderer(self):
        for style in ('microdrama', 'generic', 'long_arc'):
            text = resolve_style_file(f'vertical_9_16_{style}', 'pass2_visual')
            self.assertIn('| **Image-left-wall** (x≈0, looking toward x=1) | 1 − y | y > 0.65 | y < 0.35 |', text, style)
            self.assertIn('| **Image-right-wall** (x≈1, looking toward x=0) | y | y < 0.35 | y > 0.65 |', text, style)
            self.assertNotIn('entrance side = frame-left). X drives depth', text, style)


class PanelCameraAnchorBlock(unittest.TestCase):
    def test_canonical_view_keeps_image_x(self):
        block = artist._anchor_visibility_block(ANCHORS, 'View-From-Entrance')
        self.assertIn('img_x≈0.20', block)
        self.assertIn('H-FOV', block)

    def test_panel_camera_measures_from_itself(self):
        # Camera mid-room, right of the sofa and past it: the sofa is now behind the lens.
        block = artist._anchor_visibility_block(ANCHORS, 'View-From-Entrance', camera_xy=(0.5, 0.6))
        behind = block.split('OBJECTS BEHIND THE CAMERA')[1]
        self.assertIn('sofa', behind)
        self.assertIn('entrance-door', behind)
        ahead = block.split('OBJECTS BEHIND THE CAMERA')[0]
        self.assertIn('window', ahead)
        self.assertIn('1.2m right of camera axis', ahead)   # (0.8 - 0.5) × 4 m
        self.assertIn('(MG, ~2.4m)', ahead)                  # (1.0 - 0.6) × 6 m, Pass 2 depth band
        self.assertNotIn('img_x', block)
        self.assertNotIn('H-FOV', block)

    def test_side_wall_offset_uses_room_depth_and_mirror(self):
        # From the left wall, an entrance-side object is to the right; lateral span is room depth.
        block = artist._anchor_visibility_block(ANCHORS, 'View-From-Left-Wall', camera_xy=(0.0, 0.5))
        door_line = block.split('entrance-door')[1].split('\n')[1]
        self.assertIn('3.0m right of camera axis', door_line)  # (0.5 - 0.0) × 6 m

    def test_camera_anchor_at_lens_is_not_banned_from_frame(self):
        block = artist._anchor_visibility_block(ANCHORS, 'View-From-Entrance',
                                                frozenset({'sofa'}), camera_xy=(0.2, 0.5))
        self.assertIn('lens is at this object', block)
        self.assertNotIn('at/behind camera', block)

    def test_panel_block_resolves_anchors_by_id(self):
        # Panels name anchors by id; matching on the display label left every real panel without a block.
        tmp = _tmpdir(self)
        project = Project(output_dir=tmp, ref_dir=tmp, panels_dir=tmp)
        project.character_info = {'Office-View-From-Entrance': {'type': 'Room', 'anchor_points': ANCHORS}}
        panel = {'location_references': ['Office-View-From-Entrance'], 'camera_position': 'near sofa',
                 'camera_x': 0.2, 'camera_y': 0.3, 'state': {'anchor_refs': ['window']}}
        block = artist._panel_anchor_context(panel, project)
        self.assertIn('window (Panoramic window)', block)
        self.assertIn('sofa (Grey corner sofa)', block)
        self.assertNotIn('entrance-door', block)
        self.assertEqual(artist._extract_camera_anchor_labels('near sofa', ANCHORS), {'sofa'})

    def test_invalid_panel_camera_falls_back(self):
        self.assertIsNone(artist._panel_camera_xy({'camera_x': 1.4, 'camera_y': 0.5}))
        self.assertIsNone(artist._panel_camera_xy({'camera_x': None, 'camera_y': 0.5}))
        self.assertIsNone(artist._panel_camera_xy({}))
        self.assertEqual(artist._panel_camera_xy({'camera_x': 0, 'camera_y': 1}), (0.0, 1.0))


class OutdoorAnchorBlock(unittest.TestCase):
    def _project(self):
        tmp = _tmpdir(self)
        project = Project(output_dir=tmp, ref_dir=tmp, panels_dir=tmp)
        (tmp / 'beach-view-primary.json').write_text(json.dumps({'name': 'Beach-View-Primary', 'anchor_points': ANCHORS}))
        project.character_info = {'Beach-View-Primary': {'type': 'Outdoor', 'anchor_points': ANCHORS},
                                  'Beach-View-Opposite': {'type': 'Outdoor'}}
        return project

    def test_opposite_view_uses_primary_anchors_mirrored(self):
        panel = {'location_references': ['Beach-View-Opposite'], 'camera_position': 'near window',
                 'camera_x': 0.5, 'camera_y': 0.9, 'state': {'anchor_refs': ['sofa']}}
        block = artist._panel_anchor_context(panel, self._project())
        # sofa at x=0.2: left in View-Primary, so right of the axis when the camera turns around
        self.assertIn('1.2m right of camera axis', block)
        self.assertIn('from left edge', block)
        self.assertNotIn('entrance', block.split('OBJECTS')[0].split('Facing')[0])

    def test_switch_drops_the_block(self):
        panel = {'location_references': ['Beach-View-Primary'], 'camera_x': 0.5, 'camera_y': 0.1,
                 'state': {'anchor_refs': ['sofa']}}
        project = self._project()
        self.assertTrue(artist._panel_anchor_context(panel, project))
        with mock.patch.dict(os.environ, {'AI_PANEL_ANCHOR_BLOCK': '0'}):
            self.assertEqual(artist._panel_anchor_context(panel, project), '')


class StableRefOrder(unittest.TestCase):
    def test_refs_keep_declared_order(self):
        tmp = _tmpdir(self)
        project = Project(output_dir=tmp, ref_dir=tmp, panels_dir=tmp)
        names = ['Zed', 'Anna', 'Room-View-From-Entrance', 'Mike']
        for n in names:
            Image.new('RGB', (4, 4)).save(tmp / f'{n}.png')
            project.character_images[n] = str(tmp / f'{n}.png')
        panel = {'references': ['Zed', 'Anna', 'Zed', 'Mike'], 'location_references': ['Room-View-From-Entrance']}
        contents, opened = artist._build_ref_contents(panel, project)
        for img in opened:
            img.close()
        labels = [c for c in contents[1:] if isinstance(c, str)]
        self.assertEqual([l.split('"')[1] for l in labels], ['Zed', 'Anna', 'Mike', 'Room-View-From-Entrance'])


class PuppetDepthNamesAnchorsById(unittest.TestCase):
    def test_depth_chain_uses_ids(self):
        frame = puppet.PuppetFrame(panel_index=1, camera=puppet.CameraRig(0.5, 0.0, 0.5, 0.5, 1.0, 0.5),
                                   characters={'Anna': puppet.CharacterPose('Anna', 0.5, 0.7)},
                                   view_type='From-Entrance')
        text = puppet.compile_visual_disposition(frame, {**ANCHORS, 'zones': []})
        self.assertIn('entrance-door → sofa → Anna → window', text)
        self.assertNotIn('Grey corner sofa', text)


class SceneRefScope(unittest.TestCase):
    REFS = {
        'Anna': {'type': 'Character'},
        'black-cane': {'type': 'Object'},
        'Babka-Izba-Interior-View-From-Entrance': {'type': 'Room', 'anchor_points': {'zones': [1]}},
        'Babka-Izba-Interior-View-To-Entrance': {'type': 'Room'},
        'Bank-Hall-View-From-Entrance': {'type': 'Room', 'anchor_points': {'zones': [1]}},
        'Village-Street-View-Primary': {'type': 'Outdoor'},
    }

    def test_location_named_only_in_instructions_survives(self):
        scoped = episodes._scope_refs_to_scene(
            self.REFS, 'Village-Street-View-Primary P4 [escalation | MS | Bank-Hall-View-From-Entrance]: ...')
        self.assertIn('Bank-Hall-View-From-Entrance', scoped)
        self.assertNotIn('Babka-Izba-Interior-View-From-Entrance', scoped)

    def test_only_the_scene_location_survives(self):
        scoped = episodes._scope_refs_to_scene(self.REFS, "Babka's izba, night")
        self.assertEqual(
            set(scoped),
            {'Anna', 'black-cane', 'Babka-Izba-Interior-View-From-Entrance', 'Babka-Izba-Interior-View-To-Entrance'},
        )
        self.assertEqual(list(episodes._get_location_anchors(scoped)), ['Babka-Izba-Interior-View-From-Entrance'])

    def test_two_named_locations_both_survive(self):
        scoped = episodes._scope_refs_to_scene(self.REFS, 'Village street, then the bank hall')
        self.assertIn('Village-Street-View-Primary', scoped)
        self.assertIn('Bank-Hall-View-From-Entrance', scoped)
        self.assertNotIn('Babka-Izba-Interior-View-From-Entrance', scoped)

    def test_no_match_keeps_everything(self):
        for location in ('Изба бабки, ночь', '', 'A rooftop'):
            self.assertIs(episodes._scope_refs_to_scene(self.REFS, location), self.REFS, location)

    def test_partial_name_match_does_not_scope(self):
        refs = {'Law-Office-View-From-Entrance': {'type': 'Room'}, 'Mikhail-Cabinet-View-From-Entrance': {'type': 'Room'}}
        self.assertIs(episodes._scope_refs_to_scene(refs, "Detective's office"), refs)

    def test_generic_word_alone_does_not_match(self):
        refs = {'Living-Room-View-From-Entrance': {'type': 'Room'}, 'Interrogation-Room-View-From-Entrance': {'type': 'Room'}}
        self.assertEqual(list(episodes._scope_refs_to_scene(refs, 'Interrogation room')),
                         ['Interrogation-Room-View-From-Entrance'])


class VariationIdentityLabel(unittest.TestCase):
    def _labels(self, char):
        tmp = _tmpdir(self)
        project = Project(output_dir=tmp, ref_dir=tmp, panels_dir=tmp / 'panels')
        Image.new('RGB', (4, 4)).save(tmp / 'alisa.png')  # safe_name() lowercases ref files
        llm = _FakeImageLLM()
        artist._render_single_ref(char, {}, project, llm)
        return [r for r in llm.calls[0]['refs'] if isinstance(r, str)], llm.calls[0]['prompt']

    def test_variation_parent_is_an_identity_anchor(self):
        labels, prompt = self._labels({'name': 'Alisa-Gown', 'type': 'Character', 'visual_desc': 'gown',
                                       'style_reference': 'Alisa', 'character_ref': 'Alisa'})
        self.assertIn('SAME PERSON', labels[0])
        self.assertIn('Full-height figure', prompt)
        self.assertIn('no character sheet', prompt)
        self.assertNotIn('Close-up', prompt)

    def test_plain_style_reference_keeps_style_label(self):
        labels, prompt = self._labels({'name': 'Desk-Lamp', 'type': 'Object', 'visual_desc': 'lamp',
                                       'style_reference': 'Alisa'})
        self.assertIn('Visual style reference', labels[0])
        self.assertIn('Close-up', prompt)



class EntranceViewQACorrections(unittest.TestCase):
    def test_vfe_render_applies_qa_corrections(self):
        tmp = _tmpdir(self)
        project = Project(output_dir=tmp, ref_dir=tmp, panels_dir=tmp / 'panels')
        llm = _FakeImageLLM()
        artist._render_single_ref({'name': 'Office-View-From-Entrance', 'type': 'Room',
                                   'visual_desc': 'grey office',
                                   'qa_corrections': ['remove the second door']}, {}, project, llm)
        self.assertIn('remove the second door', llm.calls[0]['prompt'])

if __name__ == '__main__':
    unittest.main()
