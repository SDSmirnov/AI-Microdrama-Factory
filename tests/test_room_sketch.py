"""Sketch-backed room references: geometry spec, Blender render, ref injection.

No test in this module calls a paid image API. The Blender-dependent checks are
skipped when Blender is not installed.
"""
import argparse
import base64
import io
import itertools
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib.commands.setup as setup
from lib.core.project import Project
from lib.llm.openrouter import OpenRouterLLM
from lib.studio import artist, room_sketch
from lib.studio.artist import _VIEW_CAMERA, _project_image_x
from lib.studio.room_sketch import build_sketch_spec, render_sketches, resolve_room_height_m

# Trimmed copies of two real room refs (VFE with anchors + derived view JSONs).
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'room_sketch'


def _anchors(objects=None, room_m=(5.0, 8.0), **extra):
    return {
        'room_m': list(room_m),
        'objects': objects if objects is not None else [
            {'id': 'near-table', 'x': 0.2, 'y': 0.3, 'z': 0.4,
             'width_x': 0.3, 'depth_y': 0.2, 'facing_degrees_y': 180},
            {'id': 'wall-panel', 'x': 0.8, 'y': 0.7, 'z': 0.7,
             'width_x': 0.02, 'depth_y': 0.02, 'facing_degrees_y': -1},
        ],
        **extra,
    }


class SpecTests(unittest.TestCase):
    def test_door_handedness_reaches_the_sketch_spec(self):
        doors = [
            {'id': 'entrance-hatch', 'label': 'hatch', 'x': 0.5, 'y': 0.0, 'z': 0.35,
             'width_x': 0.2, 'depth_y': 0.0, 'facing_degrees_y': 180, 'hinge_side': 'x0'},
            {'id': 'side-door', 'label': 'door', 'x': 1.0, 'y': 0.4, 'z': 0.35,
             'width_x': 0.0, 'depth_y': 0.12, 'facing_degrees_y': 270, 'hinge_side': 'y1'},
            {'id': 'odd-door', 'label': 'door', 'x': 0.5, 'y': 1.0, 'z': 0.35,
             'width_x': 0.2, 'depth_y': 0.0, 'facing_degrees_y': 0, 'hinge_side': 'y0'},
        ]
        spec = build_sketch_spec(_anchors(doors), ['Room-View-To-Entrance'], {}, 'Room.')
        signs = {o['id']: o['hinge_sign'] for o in spec['objects']}
        # x0 on a wall running along x → low end; y1 on a side wall → high end;
        # a hinge side across the wall's run is ignored.
        self.assertEqual(signs, {'entrance-hatch': -1, 'side-door': 1, 'odd-door': 0})

    def test_room_height_sources(self):
        explicit = resolve_room_height_m(_anchors(room_height_m=2.6), 'nothing')
        self.assertEqual(explicit, (2.6, 'anchor_points.room_height_m'))
        described = resolve_room_height_m(_anchors(), 'steel deck, 2.6 m ceiling, rust')
        self.assertEqual(described[0], 2.6)
        self.assertEqual(described[1], 'visual_desc ceiling phrase')
        # Paraphrased double-height ceilings must not fall back to 3 m: the
        # mansion fixture says "a double-height 6m ceiling" and, in the
        # To-Entrance view, "The ceiling is a double-height 6m".
        self.assertEqual(
            resolve_room_height_m(_anchors(), '10x8m room with a double-height 6m ceiling')[0],
            6.0,
        )
        self.assertEqual(
            resolve_room_height_m(_anchors(), 'The ceiling is a double-height 6m, and the floor is concrete.')[0],
            6.0,
        )
        self.assertEqual(resolve_room_height_m(_anchors(), 'no height here')[0], 3.0)

    def test_category_heights_and_floor_placement(self):
        spec = build_sketch_spec(_anchors(), ['Room-View-From-Entrance'], {})
        table = spec['objects'][0]
        self.assertEqual(table['category'], 'table')
        self.assertAlmostEqual(table['size_m'][2], 0.75)
        # Furniture is based on the floor; the anchor z=0.4 is not its centre.
        self.assertAlmostEqual(table['center_m'][2], 0.375)

        # A wall panel keeps its anchor z but is clamped to the room.
        panel = spec['objects'][1]
        self.assertEqual(panel['category'], 'panel')
        self.assertAlmostEqual(panel['center_m'][2], 1.95)
        self.assertAlmostEqual(panel['size_m'][2], 2.1)

    def test_explicit_height_wins_over_category_default(self):
        with_height = _anchors(objects=[{
            'id': 'desk', 'x': 0.5, 'y': 0.5, 'z': 0.4,
            'width_x': 0.2, 'depth_y': 0.2, 'height_m': 0.9,
        }])
        spec = build_sketch_spec(with_height, ['Room-View-From-Entrance'], {})
        self.assertEqual(spec['objects'][0]['category'], 'table')
        self.assertEqual(spec['objects'][0]['size_m'][2], 0.9)
        self.assertAlmostEqual(spec['objects'][0]['center_m'][2], 0.45)

    def test_unmatched_objects_fall_back_to_generic(self):
        objects = [{'id': 'mystery-thing', 'label': 'Unidentified fixture',
                    'x': 0.5, 'y': 0.5, 'z': 0.5,
                    'width_x': 0.2, 'depth_y': 0.2}]
        spec = build_sketch_spec(_anchors(objects=objects), ['Room-View-From-Entrance'], {})
        obj = spec['objects'][0]
        self.assertEqual(obj['category'], 'generic')
        self.assertAlmostEqual(obj['size_m'][2], 0.6)

    def test_every_category_has_a_distinct_colour(self):
        from lib.studio.room_models import CATEGORY_HEX
        self.assertEqual(len(set(CATEGORY_HEX.values())), len(CATEGORY_HEX))
        spec = build_sketch_spec(_anchors(), ['Room-View-From-Entrance'], {})
        for obj in spec['objects']:
            self.assertEqual(len(obj['color']), 3)
            self.assertTrue(all(0.0 <= channel <= 1.0 for channel in obj['color']))

    def test_notes_do_not_override_id_and_label(self):
        from lib.studio.room_models import classify_object
        # Real fixtures describe a locker by the hatch above it and a deep
        # shelf by the monitors on it; notes must not change the category.
        self.assertEqual(classify_object({
            'id': 'life-vest-locker', 'label': 'Life-vest locker',
            'notes': 'Bolted under the watertight hatch.',
        }), 'cabinet')
        self.assertEqual(classify_object({
            'id': 'server-racks-left', 'label': 'Server racks image-left wall',
            'notes': 'Monitors and UPS units are stacked here.',
        }), 'cabinet')

    def test_legacy_anchor_ids_classify(self):
        """Ids and labels taken from 88 legacy room JSONs (anchors-from-tests)."""
        from lib.studio.room_models import classify_object
        cases = {
            # Small props and object parts are not drawn.
            ('laptop-on-table', 'laptop'): 'skip',
            ('blanket-on-sofa', 'knitted blanket'): 'skip',
            ('wall-text', "Wall Text 'Центра контроло'"): 'skip',
            ('headboard', 'Upholstered Headboard'): 'skip',
            # The id wins over prose modifiers in the label.
            ('work-counter', 'Light wood work counter'): 'counter',
            ('speaker-left', 'Black Floor-Standing Speaker North'): 'cabinet',
            ('photo-cluster-entrance-left', 'Photo Cluster (entrance wall, left of door)'): 'artwork',
            # Plural folding: shelves -> shelf, boxes -> box.
            ('far-wall-shelves', 'Shelves on dark far wall'): 'shelf',
            ('gift-boxes', 'Gift Boxes'): 'crate',
            # Ceiling fixtures are flat, not floor lamps.
            ('ceiling-light', 'Recessed Ceiling Light'): 'batten',
            ('floor-lamp', 'Floor Lamp'): 'lamp',
            ('kitchen-island', 'Kitchen Island'): 'table',
            ('stove', 'Stove'): 'cabinet',
            ('full-length-mirror', '2m tall thin-framed black mirror'): 'artwork',
            ('archway-to-living-room', 'Archway to Living Room'): 'door',
            ('panoramic-windows', 'Floor-to-Ceiling Windows'): 'window',
            ('spacesuit-1', 'Spacesuit 1'): 'column',
            ('flower-wall', 'Flower Wall Backdrop'): 'panel',
            ('dining-booth', 'dining booth'): 'sofa',
        }
        for (obj_id, label), category in cases.items():
            self.assertEqual(classify_object({'id': obj_id, 'label': label}), category, obj_id)

    def test_the_head_noun_decides_not_its_place_or_group(self):
        """The Chiomonte wine shop a weak model planned: a wall-hung crucifix drew as a 2.4 m wall panel, the card
        table as a chair, glassware on the counter as a table on the floor."""
        from lib.studio.room_models import classify_object
        cases = {'wall-crucifix': 'artwork', 'table-and-chairs': 'table', 'counter-glassware': 'skip',
                 'bar-counter': 'counter', 'back-wall': 'panel', 'wall-shelf': 'shelf', 'bar-stool': 'chair'}
        self.assertEqual({i: classify_object({'id': i}) for i in cases}, cases)

    def test_a_counter_is_floor_standing(self):
        objects = [{'id': 'bar-counter', 'x': 0.2, 'y': 0.5, 'z': 0.4, 'width_x': 0.1, 'depth_y': 0.6,
                    'height_m': 1.1, 'facing_degrees_y': 90}]
        [counter] = build_sketch_spec(_anchors(objects=objects), ['Room-View-From-Entrance'], {})['objects']
        self.assertEqual((counter['category'], counter['center_m'][2], counter['size_m'][2]), ('counter', 0.55, 1.1))

    def test_low_small_things_are_props_low_wide_ones_are_not(self):
        objects = [{'id': 'brass-tap', 'x': 0.01, 'y': 0.8, 'z': 0.4, 'width_x': 0.02, 'depth_y': 0.02,
                    'height_m': 0.25},
                   {'id': 'stage-platform', 'x': 0.5, 'y': 0.8, 'z': 0.0, 'width_x': 0.6, 'depth_y': 0.3,
                    'height_m': 0.2}]
        spec = build_sketch_spec(_anchors(objects=objects), ['Room-View-From-Entrance'], {})
        self.assertEqual([o['id'] for o in spec['objects']], ['stage-platform'])

    def test_small_props_are_not_drawn(self):
        objects = [{'id': 'mug-on-table', 'label': 'mug', 'x': 0.5, 'y': 0.5, 'z': 0.3,
                    'width_x': 0, 'depth_y': 0, 'facing_degrees_y': -1}]
        spec = build_sketch_spec(_anchors(objects=objects), ['Room-View-From-Entrance'], {})
        self.assertEqual(spec['objects'], [])

    def test_zero_footprint_gets_a_plausible_size(self):
        objects = [
            {'id': 'cream-leather-sofa', 'x': 0.5, 'y': 0.5, 'z': 0.0,
             'width_x': 0, 'depth_y': 0, 'facing_degrees_y': 90},
            {'id': 'entrance-double-doors', 'label': 'Entrance Double Doors',
             'x': 0.5, 'y': 0.0, 'z': 0.0, 'width_x': 0, 'depth_y': 0,
             'facing_degrees_y': 180},
            {'id': 'coffee-table-center', 'x': 0.98, 'y': 0.5, 'z': 0.0,
             'width_x': 0, 'depth_y': 0, 'facing_degrees_y': -1},
        ]
        sofa, door, table = build_sketch_spec(
            _anchors(objects=objects), ['Room-View-From-Entrance'], {})['objects']
        # Free-standing: local size, turned to its facing.
        self.assertEqual(sofa['size_m'][:2], [2.0, 0.9])
        self.assertEqual(sofa['yaw_degrees'], 90.0)
        # Wall-mounted: on the nearest wall, double-door span.
        self.assertAlmostEqual(door['center_m'][1], 0.05)
        self.assertEqual(door['size_m'][:2], [1.6, 0.1])
        # Keyword height and footprint; pulled inside the room.
        self.assertAlmostEqual(table['size_m'][2], 0.45)
        self.assertLessEqual(table['center_m'][0] + 0.55, 5.0 + 1e-9)

    def test_legacy_mansion_ids_classify(self):
        from lib.studio.room_models import classify_object
        self.assertEqual(classify_object({
            'id': 'entrance-doorway', 'label': 'Entrance Doorway',
        }), 'door')
        # "Display" must not beat "shelving".
        self.assertEqual(classify_object({
            'id': 'display-shelving-wall', 'label': 'Display Shelving Wall',
        }), 'shelf')
        self.assertEqual(classify_object({
            'id': 'monitor-rack-bolted', 'label': 'Bolted monitor rack frame',
        }), 'monitor')
        self.assertEqual(classify_object({
            'id': 'bar-section', 'label': 'Bar Section',
        }), 'counter')
        self.assertEqual(classify_object({
            'id': 'artwork-on-entrance-wall', 'label': 'Artwork on entrance wall',
        }), 'artwork')

    def test_wall_spanning_features_reach_the_ceiling(self):
        anchors = {
            'room_m': [10.0, 8.0],
            'objects': [
                {'id': 'fireplace-feature-wall', 'label': 'Fireplace feature wall',
                 'x': 0.15, 'y': 0.4, 'z': 0.5,
                 'width_x': 0.3, 'depth_y': 0.125},
                {'id': 'far-window-wall', 'label': 'Far window wall',
                 'x': 0.5, 'y': 1.0, 'z': 0.5,
                 'width_x': 1.0, 'depth_y': 0.01},
                {'id': 'display-shelving-wall', 'label': 'Display shelving wall',
                 'x': 0.98, 'y': 0.5, 'z': 0.5,
                 'width_x': 0.04, 'depth_y': 1.0},
                {'id': 'artwork-on-entrance-wall', 'label': 'Artwork on entrance wall',
                 'x': 0.65, 'y': 0.01, 'z': 0.6,
                 'width_x': 0, 'depth_y': 0},
            ],
        }
        spec = build_sketch_spec(anchors, ['Room-View-From-Entrance'], {}, '6 m ceiling')
        by_id = {obj['id']: obj for obj in spec['objects']}
        for obj in spec['objects']:
            if obj['id'] == 'artwork-on-entrance-wall':
                continue  # wall art hangs at human height, not floor-to-ceiling
            self.assertAlmostEqual(obj['size_m'][2], 6.0, msg=obj['id'])
            self.assertAlmostEqual(obj['center_m'][2], 3.0, msg=obj['id'])

        # The fireplace is declared 3 m across the room; snap it flat to the
        # nearest (left) wall with its 3 m span running along the wall.
        fireplace = by_id['fireplace-feature-wall']
        self.assertAlmostEqual(fireplace['center_m'][0], 0.25)
        self.assertAlmostEqual(fireplace['center_m'][1], 3.2)
        self.assertAlmostEqual(fireplace['size_m'][0], 0.5)
        self.assertAlmostEqual(fireplace['size_m'][1], 3.0)

        # Already wall-aligned features keep their declared footprint.
        window = by_id['far-window-wall']
        self.assertAlmostEqual(window['center_m'][1], 8.0 - 0.04)
        self.assertAlmostEqual(window['size_m'][0], 10.0)
        self.assertAlmostEqual(window['size_m'][1], 0.08)

        shelving = by_id['display-shelving-wall']
        self.assertAlmostEqual(shelving['center_m'][0], 10.0 - 0.2)
        self.assertAlmostEqual(shelving['size_m'][0], 0.4)
        self.assertAlmostEqual(shelving['size_m'][1], 8.0)

        # Art anchors often have zero width/depth: give them a framed panel
        # on the nearest wall instead of a 5 cm post.
        artwork = by_id['artwork-on-entrance-wall']
        self.assertAlmostEqual(artwork['center_m'][1], 0.03)
        self.assertAlmostEqual(artwork['size_m'][0], 1.2)
        self.assertAlmostEqual(artwork['size_m'][1], 0.06)
        self.assertAlmostEqual(artwork['size_m'][2], 0.8)

    def test_fixture_objects_are_mostly_recognisable(self):
        categories = set()
        generic = 0
        for stem in ('heping-7-hold-view-from-entrance',
                     'warehouse-breach-view-from-entrance'):
            data = json.loads((FIXTURE / f'{stem}.json').read_text())
            spec = build_sketch_spec(
                data['anchor_points'], ['Room-View-From-Entrance'], {},
                data.get('visual_desc', ''),
            )
            for obj in spec['objects']:
                categories.add(obj['category'])
                generic += obj['category'] == 'generic'
        self.assertLessEqual(generic, 3, f'too many generic objects: {sorted(categories)}')
        self.assertTrue(
            {'table', 'shelf', 'monitor', 'door', 'extinguisher', 'spool'} <= categories,
            f'missing recognisable categories: {sorted(categories)}',
        )

    def test_camera_spec_and_aspect(self):
        spec = build_sketch_spec(
            _anchors(), ['Room-View-From-Entrance', 'Room-View-To-Entrance'], {}
        )
        first, second = spec['views']
        # VFE is the 90° inventory master from the entrance wall plane, behind the 0.5 m cut.
        self.assertEqual(first['position_m'][:2], [2.5, 0.02 * 8])
        self.assertEqual(first['hfov_degrees'], 90.0)
        self.assertEqual(second['position_m'][:2], [2.5, 0.98 * 8 - 0.5])
        self.assertEqual(second['forward'], [0.0, -1.0])
        # A natural lens frames the 5 m wall from the cut plane: no setback.
        self.assertEqual(second['hfov_degrees'], 55.0)
        self.assertIsNone(second['clip_start_m'])
        # 5 m wide x 8 m deep x 3 m fallback ceiling: the view faces the
        # 5 x 3 wall, so it is landscape (16:9), not the old plan-ratio 3:4.
        self.assertEqual((first['width_px'], first['height_px']), (1024, 576))

    def test_narrow_room_side_view_stands_behind_the_removed_wall(self):
        # heping-7-server-hold: 3.8 x 6.5 x 2.8 m, racks along the right wall.
        objects = [
            {'id': 'desk-left-wall', 'x': 0.1, 'y': 0.3, 'z': 0.3,
             'width_x': 0.2, 'depth_y': 0.2},
            {'id': 'server-racks-right', 'x': 0.88, 'y': 0.5, 'z': 0.4,
             'width_x': 0.22, 'depth_y': 0.72},
        ]
        side, = build_sketch_spec(
            _anchors(objects=objects, room_m=(3.8, 6.5), room_height_m=2.8),
            ['Room-View-From-Left-Wall'], {})['views']
        # Capped 3 m behind the left wall; the lens widens past 55° to compensate.
        self.assertAlmostEqual(side['position_m'][0], 0.02 * 3.8 - 3.0)
        self.assertGreater(side['hfov_degrees'], 55.0)
        self.assertLessEqual(side['hfov_degrees'], 90.0)
        # The desk centred before the cut is hidden; the clip removes the wall
        # but stops at the racks' front face.
        self.assertEqual(side['culled_ids'], ['desk-left-wall'])
        wall_gap = 0.02 * 3.8 - side['position_m'][0]
        self.assertGreater(side['clip_start_m'], wall_gap)
        self.assertLessEqual(side['clip_start_m'], 3.5)

    def test_rig_keeps_center_and_by_views(self):
        names = ['Room-View-Center-To-Far', 'Room-View-By-Far-Wall']
        center, by_wall = build_sketch_spec(_anchors(room_m=(4.5, 6.5)), names, {})['views']
        # 4.5 m far wall (+15% margin) from the 3.25 m centre; no cut.
        self.assertAlmostEqual(center['hfov_degrees'], 77.0, delta=0.1)
        self.assertNotIn('clip_start_m', center)
        self.assertEqual(by_wall['hfov_degrees'], 110)

    def test_floor_before_the_cut_never_leaves_a_void(self):
        from lib.studio.artist import _view_rig
        from lib.studio.room_geometry import CAMERA_HEIGHT_M
        for room_m, height in (((3.8, 6.5), 2.8), ((5.0, 4.0), 2.7), ((2.5, 2.5), 2.4)):
            for suffix in ('View-From-Entrance', 'View-From-Left-Wall'):
                hfov, back = _view_rig(suffix, room_m, height)
                aspect = artist._view_aspect_ratio(suffix, room_m, {}, height)
                aw, ah = (int(p) for p in aspect.split(':'))
                floor_hit = CAMERA_HEIGHT_M / (math.tan(math.radians(hfov) / 2) * ah / aw)
                self.assertGreaterEqual(floor_hit + 1e-6, back, f'{room_m} {suffix}')

    def test_prompt_lens_matches_the_sketch(self):
        names = [f'Room-View-{s}' for s in ('From-Entrance', 'To-Entrance',
                                             'From-Left-Wall', 'From-Right-Wall')]
        anchors = _anchors(room_m=(3.8, 6.5), room_height_m=2.8)
        for view in build_sketch_spec(anchors, names, {})['views']:
            block = artist._anchor_visibility_block(
                anchors, view['suffix'], camera_inset_m=0.5)
            self.assertIn(f"H-FOV:    ~{view['hfov_degrees']:.0f}°", block, view['suffix'])

    def test_center_and_by_views_do_not_inset(self):
        # Their canonical positions already encode a distance from a wall.
        spec = build_sketch_spec(
            _anchors(),
            ['Room-View-Center-To-Far', 'Room-View-By-Entrance'],
            {},
        )
        center, by_entrance = spec['views']
        self.assertEqual(center['position_m'][:2], [2.5, 4.0])
        self.assertEqual(by_entrance['position_m'][:2], [2.5, 0.15 * 8])

    def test_view_aspect_uses_room_cross_section_not_plan_ratio(self):
        from lib.studio.artist import _view_aspect_ratio
        # 5 m wide x 8 m deep x 2.6 m high. The entrance view faces the
        # 5 x 2.6 wall, so it is landscape even though the plan is portrait.
        self.assertEqual(
            _view_aspect_ratio('View-From-Entrance', (5.0, 8.0), {}, 2.6), '16:9'
        )
        # The left-wall view faces the 8 x 2.6 wall, so it is wider.
        self.assertEqual(
            _view_aspect_ratio('View-From-Left-Wall', (5.0, 8.0), {}, 2.6), '21:9'
        )
        # A tall narrow room still gets a portrait view when its wall is
        # taller than it is wide.
        self.assertEqual(
            _view_aspect_ratio('View-From-Entrance', (2.0, 8.0), {}, 4.0), '9:16'
        )

    def test_view_aspect_falls_back_without_dimensions(self):
        from lib.studio.artist import _view_aspect_ratio
        config = {'reference_characters': {'ref_aspect_ratio': '4:5'}}
        self.assertEqual(
            _view_aspect_ratio('View-From-Entrance', None, config, 2.6), '4:5'
        )

    def test_wall_views_stand_at_the_cut_when_a_natural_lens_fits(self):
        # Wide room: no setback, the camera stays at the cut, 0.5 m inside.
        spec = build_sketch_spec(
            _anchors(room_m=(12.0, 8.0)), ['Room-View-From-Left-Wall', 'Room-View-From-Right-Wall'], {}
        )
        left, right = spec['views']
        # 12 m deep enough for 55° to frame the 8 m wall from the cut.
        self.assertEqual(left['position_m'][:2], [0.02 * 12 + 0.5, 4.0])
        self.assertEqual(right['position_m'][:2], [0.98 * 12 - 0.5, 4.0])
        self.assertEqual(left['hfov_degrees'], 55.0)

    def test_yaw_follows_facing_convention(self):
        objects = [{'id': 'desk', 'x': 0.5, 'y': 0.5, 'z': 0.5,
                    'width_x': 0.04, 'depth_y': 0.025, 'facing_degrees_y': 45}]
        spec = build_sketch_spec(
            _anchors(objects=objects), ['Room-View-From-Entrance'], {}
        )
        self.assertEqual(spec['objects'][0]['yaw_degrees'], 45.0)

    def test_elongated_rows_keep_axis_aligned_footprints(self):
        objects = [{'id': 'server-racks-left', 'x': 0.12, 'y': 0.48, 'z': 0.4,
                    'width_x': 0.22, 'depth_y': 0.72, 'facing_degrees_y': 90}]
        spec = build_sketch_spec(
            _anchors(objects=objects), ['Room-View-From-Entrance'], {}
        )
        # Rotating this row by 90 degrees would turn it across the room.
        self.assertEqual(spec['objects'][0]['yaw_degrees'], 0.0)

    def test_fallback_boxes_stay_inside_room(self):
        for stem in ('heping-7-hold-view-from-entrance',
                     'warehouse-breach-view-from-entrance'):
            data = json.loads((FIXTURE / f'{stem}.json').read_text())
            spec = build_sketch_spec(
                data['anchor_points'], ['Room-View-From-Entrance'], {},
                data.get('visual_desc', ''),
            )
            room_h = spec['room_m'][2]
            for obj in spec['objects']:
                low = obj['center_m'][2] - obj['size_m'][2] / 2
                high = obj['center_m'][2] + obj['size_m'][2] / 2
                self.assertGreaterEqual(low, -1e-6, f'{stem}/{obj["id"]} below floor')
                self.assertLessEqual(high, room_h + 1e-6, f'{stem}/{obj["id"]} above ceiling')

    def test_high_surface_features_are_thin(self):
        objects = [{'id': 'partial-roof-span', 'x': 0.5, 'y': 0.5, 'z': 0.98,
                    'width_x': 0.85, 'depth_y': 0.7}]
        spec = build_sketch_spec(
            _anchors(objects=objects, room_height_m=4.0), ['Room-View-From-Entrance'], {}
        )
        roof = spec['objects'][0]
        self.assertEqual(roof['category'], 'panel')
        self.assertLessEqual(roof['size_m'][2], 0.25)
        self.assertGreater(roof['size_m'][2], 0.15)
        self.assertLessEqual(roof['center_m'][2] + roof['size_m'][2] / 2, 4.0)

    def test_invalid_room_dimensions_are_rejected(self):
        for bad in ({'room_m': None}, _anchors(room_m=(0, 8)), _anchors(room_m=(5,))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_sketch_spec(bad, ['Room-View-From-Entrance'], {})


class CreateOnlyTests(unittest.TestCase):
    def test_derived_jsons_get_material_reference_without_pngs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp)
            name = 'Test-Room'
            (ref_dir / 'test-room.json').write_text(json.dumps({
                'name': name, 'type': 'Room',
                'visual_desc': 'Steel room, 5m wide by 8m deep.',
                'logline_subject_info': 'A test room',
                'video_visual_desc': '', 'style_reference': '',
            }))
            project = Project()
            project.ref_dir = ref_dir
            artist.remake_room_refs({}, object(), project, create_only=True)
            created = sorted(ref_dir.glob('test-room-view-*.json'))
            self.assertGreaterEqual(len(created), 6)
            self.assertEqual(list(ref_dir.glob('*.png')), [])
            for path in created:
                data = json.loads(path.read_text())
                expected = '' if data['name'].endswith('View-From-Entrance') else (
                    f'{name}-View-From-Entrance'
                )
                self.assertEqual(data['style_reference'], expected, path.name)


class InjectionTests(unittest.TestCase):
    class CapturingLLM:
        def __init__(self):
            self.prompt = ''
            self.refs = []
            self.image_bytes = []
            self.kwargs = {}

        def make_image(self, prompt, refs=None, **kwargs):
            self.prompt = prompt
            self.refs = refs or []
            self.kwargs = kwargs
            # _render_single_ref closes PIL images in finally; snapshot their
            # bytes now so later API-payload checks do not touch closed files.
            for ref in self.refs:
                if hasattr(ref, 'save'):
                    buf = io.BytesIO()
                    ref.save(buf, format='PNG')
                    self.image_bytes.append(buf.getvalue())
            return b'image-bytes'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir
        self.base = 'Test-Room'
        self.entrance = f'{self.base}-View-From-Entrance'
        self.to_entrance = f'{self.base}-View-To-Entrance'
        self.derived = f'{self.base}-View-From-Left-Wall'
        grays = {
            self.entrance: 30,
            self.to_entrance: 60,
            self.derived: 90,
        }
        for name, gray in grays.items():
            # remake-room-refs --json-only leaves style_reference empty for
            # most derived views; injection must supply the truth PNGs itself.
            data = {'name': name, 'type': 'Room', 'visual_desc': 'Steel room.',
                    'style_reference': ''}
            (self.ref_dir / f'{name.lower()}.json').write_text(json.dumps(data))
            Image.new('RGB', (4, 4), (gray, gray, gray)).save(
                self.ref_dir / f'{name.lower()}.png'
            )
        Image.new('RGB', (4, 4), (200, 200, 200)).save(
            room_sketch.sketch_path(self.ref_dir, self.derived)
        )

    def _render(self, name, llm):
        info = json.loads((self.ref_dir / f'{name.lower()}.json').read_text())
        artist._render_single_ref(info, {}, self.project, llm, force=True)

    def test_sketch_leads_refs_and_prompt_names_all_truths(self):
        llm = self.CapturingLLM()
        self._render(self.derived, llm)
        # 3 images + 3 labels: sketch, VFE, VTE.
        self.assertEqual(len(llm.refs), 6)
        self.assertEqual(llm.refs[0].filename, str(room_sketch.sketch_path(self.ref_dir, self.derived)))
        self.assertIn('IMAGE 1 — LAYOUT SKETCH', llm.refs[1])
        self.assertEqual(llm.refs[2].filename, str(self.ref_dir / f'{self.entrance.lower()}.png'))
        self.assertIn('IMAGE 2 — BASE TRUTH', llm.refs[3])
        self.assertEqual(llm.refs[4].filename, str(self.ref_dir / f'{self.to_entrance.lower()}.png'))
        self.assertIn('IMAGE 3 — SECOND TRUTH', llm.refs[5])
        self.assertIn('TRUTH CONTRACT', llm.prompt)

    def test_vte_uses_vfe_alone_even_when_sketch_exists(self):
        llm = self.CapturingLLM()
        self._render(self.to_entrance, llm)
        self.assertEqual(len(llm.refs), 2)
        self.assertEqual(llm.refs[0].filename, str(self.ref_dir / f'{self.entrance.lower()}.png'))
        self.assertIn('IMAGE 1 — BASE TRUTH', llm.refs[1])
        self.assertNotIn('LAYOUT SKETCH', llm.prompt)
        self.assertIn('180-degree turn', llm.prompt)

    def test_render_prompt_hides_what_is_behind_the_camera(self):
        llm = self.CapturingLLM()
        self._render(self.to_entrance, llm)
        self.assertIn('BEHIND THE CAMERA, NOT VISIBLE: the far wall with its windows', llm.prompt)
        self.assertIn('never print them', llm.prompt)

    def test_room_view_aspect_uses_physical_dimensions(self):
        json_path = self.ref_dir / f'{self.to_entrance.lower()}.json'
        data = json.loads(json_path.read_text())
        data['room_dims'] = [5.0, 8.0]
        data['visual_desc'] = 'Steel room, 2.6 m ceiling.'
        json_path.write_text(json.dumps(data))
        llm = self.CapturingLLM()
        self._render(self.to_entrance, llm)
        # Facing the 5 m entrance wall in a 2.6 m room -> 5:2.6 -> nearest supported 16:9.
        self.assertEqual(llm.kwargs.get('aspect_ratio'), '16:9')
        self.assertIn('FRAMING: this view faces a 5.0 m wide, 2.6 m high wall', llm.prompt)
        self.assertIn('16:9 frame', llm.prompt)

    def test_existing_style_reference_is_not_duplicated(self):
        json_path = self.ref_dir / f'{self.derived.lower()}.json'
        data = json.loads(json_path.read_text())
        data['style_reference'] = self.entrance
        json_path.write_text(json.dumps(data))
        llm = self.CapturingLLM()
        self._render(self.derived, llm)
        self.assertEqual(len(llm.refs), 6)
        self.assertEqual(len(llm.image_bytes), 3)
        self.assertEqual(llm.refs[0].filename, str(room_sketch.sketch_path(self.ref_dir, self.derived)))
        self.assertEqual(llm.refs[2].filename, str(self.ref_dir / f'{self.entrance.lower()}.png'))
        self.assertEqual(llm.refs[4].filename, str(self.ref_dir / f'{self.to_entrance.lower()}.png'))

    def test_no_sketch_still_uses_both_truth_views(self):
        room_sketch.sketch_path(self.ref_dir, self.derived).unlink()
        json_path = self.ref_dir / f'{self.derived.lower()}.json'
        data = json.loads(json_path.read_text())
        data['style_reference'] = self.entrance
        json_path.write_text(json.dumps(data))
        llm = self.CapturingLLM()
        self._render(self.derived, llm)
        self.assertEqual(len(llm.refs), 4)
        self.assertEqual(llm.refs[0].filename, str(self.ref_dir / f'{self.entrance.lower()}.png'))
        self.assertEqual(llm.refs[2].filename, str(self.ref_dir / f'{self.to_entrance.lower()}.png'))
        self.assertNotIn('IMAGE 1 — LAYOUT SKETCH', llm.prompt)

    def test_canonical_entrance_never_gets_sketch_injection(self):
        Image.new('RGB', (4, 4), (200, 200, 200)).save(
            room_sketch.sketch_path(self.ref_dir, self.entrance)
        )
        llm = self.CapturingLLM()
        self._render(self.entrance, llm)
        self.assertEqual(llm.refs, [])
        self.assertNotIn('IMAGE 1', llm.prompt)

    def test_image_api_keeps_sketch_first(self):
        llm = self.CapturingLLM()
        self._render(self.derived, llm)
        # Use the snapshotted image bytes (sketch, VFE, VTE) because the PIL
        # objects in llm.refs are closed after _render_single_ref returns.
        self.assertEqual(len(llm.image_bytes), 3)
        backend = OpenRouterLLM(api_key='k', text_model='text', image_model='image')
        with mock.patch.object(backend, '_post_image_api', return_value={
                'data': [{'b64_json': 'aGk='}]}):
            backend._make_image_via_api('PROMPT', refs=llm.image_bytes)
        parts = backend._refs_to_image_api(llm.image_bytes)[0]
        self.assertEqual(len(parts), 3)
        images = []
        for part in parts:
            encoded = part['image_url']['url'].split(',', 1)[1]
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as img:
                images.append(sum(img.convert('L').getdata()) / (img.width * img.height))
        # Sketch (200 gray) precedes entrance reference (30 gray).
        self.assertGreater(images[0], images[1])


class CommitTests(unittest.TestCase):
    """Commit and stale-marking behavior, exercised without Blender."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        (self.ref_dir / 'commit-room-view-from-entrance.json').write_text(json.dumps({
            'name': 'Commit-Room-View-From-Entrance', 'type': 'Room',
            'visual_desc': 'Room.', 'anchor_points': _anchors(),
        }))
        self.view_json = self.ref_dir / 'commit-room-view-to-entrance.json'
        self.view_json.write_text(json.dumps({
            'name': 'Commit-Room-View-To-Entrance', 'type': 'Room',
            'visual_desc': 'Room.', 'style_reference': '',
        }))
        self.project = Project()
        self.project.ref_dir = self.ref_dir

    @staticmethod
    def _fake_blender(spec_path, meta_path, blender_cmd):
        spec = json.loads(spec_path.read_text())
        for output in spec['outputs']:
            Path(output).write_bytes(b'sketch-bytes')

    def test_unchanged_sketches_do_not_remark_views_stale(self):
        with mock.patch.object(room_sketch, '_render_views', side_effect=self._fake_blender):
            self.assertGreater(len(render_sketches(self.project, {})), 0)
            data = json.loads(self.view_json.read_text())
            data.pop('needs_regenerate', None)
            self.view_json.write_text(json.dumps(data))
            render_sketches(self.project, {})
        self.assertNotIn('needs_regenerate', json.loads(self.view_json.read_text()))

    def test_sketch_change_does_not_mark_vte_stale(self):
        derived = self.ref_dir / 'commit-room-view-from-left-wall.json'
        derived.write_text(json.dumps({
            'name': 'Commit-Room-View-From-Left-Wall', 'type': 'Room',
            'visual_desc': 'Room.', 'style_reference': '',
        }))
        with mock.patch.object(room_sketch, '_render_views', side_effect=self._fake_blender):
            render_sketches(self.project, {})
        self.assertTrue(json.loads(derived.read_text())['needs_regenerate'])
        self.assertNotIn('needs_regenerate', json.loads(self.view_json.read_text()))

    def test_commit_failure_rolls_back_previous_sketches(self):
        with mock.patch.object(room_sketch, '_render_views', side_effect=self._fake_blender):
            render_sketches(self.project, {})
        before = {p.name: p.read_bytes() for p in self.ref_dir.glob('*.sketch.png')}
        original_write = Path.write_bytes
        state = {'failed': False}

        def flaky(self, data):
            if self.name.endswith('.sketch.png.tmp') and not state['failed']:
                state['failed'] = True
                raise OSError('simulated disk failure')
            return original_write(self, data)

        with mock.patch.object(room_sketch, '_render_views', side_effect=self._fake_blender), \
                mock.patch.object(Path, 'write_bytes', flaky):
            with self.assertRaises(RuntimeError):
                render_sketches(self.project, {})
        after = {p.name: p.read_bytes() for p in self.ref_dir.glob('*.sketch.png')}
        self.assertEqual(after, before)
        self.assertEqual(list(self.ref_dir.glob('*.sketch.png.tmp')), [])


    def test_outdoor_view_with_nothing_in_frame_gets_no_sketch(self):
        (self.ref_dir / 'yard-view-primary.json').write_text(json.dumps({
            'name': 'Yard-View-Primary', 'type': 'Outdoor', 'visual_desc': 'Yard.',
            'anchor_points': {'room_m': [30, 40], 'station': [0.5, 0.45], 'objects': [
                {'id': 'main-facade', 'label': 'Facade', 'x': 0.5, 'y': 0.95, 'width_x': 0.9, 'depth_y': 0.1},
                {'id': 'iron-gate', 'label': 'Gate', 'x': 0.5, 'y': 0.05, 'width_x': 0.15, 'depth_y': 0.02}]}}))
        side = self.ref_dir / 'yard-view-ortho-primary.json'
        side.write_text(json.dumps({'name': 'Yard-View-Ortho-Primary', 'type': 'Outdoor', 'visual_desc': 'Side.'}))
        stale = room_sketch.sketch_path(self.ref_dir, 'Yard-View-Ortho-Primary')
        stale.write_bytes(b'old blank sketch')

        def fake(spec_path, meta_path, blender_cmd):
            self._fake_blender(spec_path, meta_path, blender_cmd)
            meta_path.write_text(json.dumps(room_sketch._view_meta(json.loads(spec_path.read_text()))))

        with mock.patch.object(room_sketch, '_render_views', side_effect=fake):
            rendered = render_sketches(self.project, {}, room_filter={'Yard'})
        self.assertEqual(sorted(rendered), ['Yard-View-Opposite'])  # the gate is in frame
        self.assertFalse(stale.exists())
        self.assertTrue(json.loads(side.read_text())['needs_regenerate'])


@unittest.skipUnless(shutil.which('blender'), 'Blender is not installed')
@pytest.mark.blender
class BlenderSketchTests(unittest.TestCase):
    def _project(self, fixture_copy, base):
        project = Project()
        project.ref_dir = fixture_copy
        meta_dir = fixture_copy.parent / 'meta'
        rendered = render_sketches(project, {}, meta_dir=meta_dir)
        self.assertGreater(len(rendered), 0)
        for path in rendered.values():
            with Image.open(path) as img:
                self.assertGreater(len(set(img.convert('RGB').getdata())), 1)
        source = json.loads((fixture_copy / f'{base}.json').read_text())
        entrance_name = source['name']
        base_name = entrance_name[: -(len('View-From-Entrance') + 1)]
        # Production names the meta sidecar from the JSON `name`, not the filename.
        meta = json.loads(
            (meta_dir / f'{room_sketch.safe_name(base_name)}.meta.json').read_text()
        )
        return meta, source['anchor_points'], base_name

    def _assert_ordering(self, meta, anchors, base_name, suffix):
        camera = _VIEW_CAMERA[suffix]
        view_meta = meta[f'{base_name}-{suffix}']
        objects = {o['id']: o for o in anchors['objects']}
        checked = 0
        for id_a, id_b in itertools.combinations(objects, 2):
            a, b = objects[id_a], objects[id_b]
            expected_a = _project_image_x(float(a['x']), float(a['y']), suffix)
            expected_b = _project_image_x(float(b['x']), float(b['y']), suffix)
            if abs(expected_a - expected_b) < 0.2:
                continue
            depth_a = float(a['y']) if camera[3] > 0 else 1 - float(a['y'])
            depth_b = float(b['y']) if camera[3] > 0 else 1 - float(b['y'])
            if camera[2] != 0:
                depth_a = float(a['x']) if camera[2] > 0 else 1 - float(a['x'])
                depth_b = float(b['x']) if camera[2] > 0 else 1 - float(b['x'])
            if abs(depth_a - depth_b) > 0.12:
                continue
            pair_a = view_meta.get(id_a)
            pair_b = view_meta.get(id_b)
            # Any lens: order must hold for objects ahead of the camera, in or
            # near the frame. Centres at the lens plane project to huge |img_x|.
            if not all(p and p['in_front'] and -1.0 <= p['img_x'] <= 2.0
                       for p in (pair_a, pair_b)):
                continue
            checked += 1
            self.assertGreater(
                (expected_a - expected_b) * (pair_a['img_x'] - pair_b['img_x']), 0,
                f'{suffix}: {id_a} vs {id_b} reversed',
            )
        return checked

    def test_real_room_fixtures_render_with_correct_lateral_ordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'refs'
            target.mkdir()
            for name in ('heping-7-hold', 'warehouse-breach'):
                for source in FIXTURE.glob(f'{name}-*.json'):
                    shutil.copyfile(source, target / source.name)
            for base in ('heping-7-hold-view-from-entrance',
                         'warehouse-breach-view-from-entrance'):
                meta, anchors, base_name = self._project(target, base)
                checked_total = 0
                for suffix in ('View-To-Entrance', 'View-From-Left-Wall',
                               'View-From-Right-Wall', 'View-Center-To-Entrance'):
                    checked_total += self._assert_ordering(meta, anchors, base_name, suffix)
                self.assertGreater(checked_total, 10,
                                   f'{base_name}: not enough comparable object pairs')

    def test_blender_failure_leaves_no_sketches(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp)
            name = 'Failure-Room-View-From-Entrance'
            (ref_dir / f'{name.lower()}.json').write_text(json.dumps({
                'name': name, 'type': 'Room', 'visual_desc': 'Room.',
                'anchor_points': _anchors(),
            }))
            project = Project()
            project.ref_dir = ref_dir
            with self.assertRaises(RuntimeError):
                render_sketches(project, {}, blender_cmd='no-such-blender-binary')
            self.assertEqual(list(ref_dir.glob('*.sketch.png')), [])


class WiringTests(unittest.TestCase):
    def test_cli_registers_new_flags_and_command(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        setup.register(sub)
        refs = parser.parse_args(['refs', '--entrance-views-only'])
        self.assertTrue(refs.entrance_views_only)
        self.assertEqual(refs.func, setup.cmd_refs)
        remake = parser.parse_args(['remake-room-refs', '--json-only'])
        self.assertTrue(remake.create_only)
        sketches = parser.parse_args(['room-sketches'])
        self.assertEqual(sketches.func, setup.cmd_room_sketches)
        views = parser.parse_args(['room-views', '--rooms', 'A,B', '--no-sketches'])
        self.assertEqual(views.func, setup.cmd_room_views)
        self.assertEqual(views.rooms, 'A,B')
        self.assertTrue(views.no_sketches)

    def test_makefile_has_geometry_first_chain(self):
        makefile = (Path(__file__).resolve().parents[1] / 'Makefile').read_text()
        self.assertIn('draft-with-sketches:', makefile)
        self.assertIn('$(MAKE) room-views\n', makefile)
        self.assertIn('room-views:', makefile)
        # The legacy low-level targets stay available for manual recovery.
        self.assertIn('remake-room-refs:', makefile)
        self.assertIn('refs --entrance-views-only', makefile)


if __name__ == '__main__':
    unittest.main()
