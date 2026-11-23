"""Car-interior blocking: seats, shot choice, projection, aspect handling, prompt/QA wiring."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.schemas import PANEL_STATE_SCHEMA, VEHICLE_POSITIONS
from lib.studio import vehicle_geometry as vg
from lib.studio.artist.render_utils import _ref_label
from lib.studio.blocking_sketch import render_blockings, sketch_path
from lib.studio.render3d.factory import get_engine

SUV = {'name': 'Black-SUV-Exterior', 'type': 'Vehicle', 'visual_desc': 'A large black SUV.'}


def shot_ids(body_key):
    seats = [s for s in vg.SEATS if vg.BODIES[body_key].third_y is not None or not s.startswith('third')]
    pairs = [f'{m}:{a}>{b}' for m in ('pov', 'ots') for a in seats for b in seats if a != b]
    return [*vg.SHOT_DESCRIPTIONS, *(f'side-{s}' for s in seats if s in vg.SIDE_SEATS),
            'dash-driver', 'dash-front-passenger', *(f'lap-{s}' for s in seats), *pairs]


def actor(name, position, in_frame=True, gaze=None, seat=None):
    return {'name': name, 'visual_ref': name, 'position': position, 'in_frame': in_frame,
            'gaze_target': gaze, 'vehicle_position': seat}


def panel(actors, scale='MS', camera_position='', **extra):
    return {'panel_index': 1, 'scale': scale, 'camera_position': camera_position,
            'location_references': ['Black-SUV-Interior-To-Entrance'],
            'references': [a['name'] for a in actors], 'state': {'actors': actors}, **extra}


# The mafia-scenes scene 2 blocking: kidnapper behind the driver, girl behind the passenger.
REAR_PAIR = [
    actor('Driver', "in the driver's seat", in_frame=False),
    actor('Kidnapper', 'in the rear driver-side seat', gaze='Girl'),
    actor('Girl', 'in the rear passenger-side seat', gaze='Kidnapper'),
]


def blocking(p, aspect='9:16', refs=None):
    refs = refs if refs is not None else {'Black-SUV-Exterior': SUV}
    return vg.panel_blocking(p, None, refs.get, aspect)


def place(b, name):
    occ = next(o for o in b.occupants if o.name == name)
    return vg._placement(b.camera, occ, b.body, b.side)


class SeatTests(unittest.TestCase):
    def test_legacy_free_text_maps_to_seats(self):
        cases = {
            "in the driver's seat of the Black-SUV": 'driver',
            'in the rear driver-side seat, 40cm from The-Girl': 'rear-left',
            'in the rear passenger-side seat of the moving SUV': 'rear-right',
            'in the middle of the back seat': 'rear-center',
            'front passenger seat': 'front-passenger',
            'on the sidewalk, 2m from the car': None,
            'rear-right': 'rear-right',
        }
        for text, seat in cases.items():
            self.assertEqual(vg.infer_seat(text), seat, text)

    def test_driver_side_follows_drive_side(self):
        self.assertEqual(vg.infer_seat('rear driver-side seat', 'rhd'), 'rear-right')
        self.assertGreater(vg.seat_xy('driver', vg.BODIES['sedan'], 'rhd')[0], 0)

    def test_schema_enum_covers_every_seat(self):
        self.assertTrue(set(vg.SEATS) <= set(VEHICLE_POSITIONS))
        self.assertIn('vehicle_position', PANEL_STATE_SCHEMA['properties']['actors']['items']['required'])

    def test_gaze_takes_the_first_named_occupant_and_doors(self):
        occ = vg.occupants(panel([actor('Driver', 'driver'), actor('Kidnapper', 'rear-left'),
                                  actor('Girl', 'rear-right', gaze="The-Kidnapper, then The-Driver's head")]),
                           'lhd', vg.BODIES['suv'])
        self.assertEqual(occ[-1].gaze_seat, 'rear-left')
        occ = vg.occupants(panel([actor('Girl', 'rear-right', gaze='door handle')]), 'lhd', vg.BODIES['suv'])
        self.assertEqual(occ[0].gaze, 'window')

    def test_explicit_non_seat_does_not_fall_back_to_position_text(self):
        standing = actor('Father', 'by the rear left door', seat='outside')
        legacy = actor('Kidnapper', 'in the rear left seat')
        names = [o.name for o in vg.occupants(panel([standing, legacy]), 'lhd', vg.BODIES['suv'])]
        self.assertEqual(names, ['Kidnapper'])

    def test_ambiguous_words_do_not_seat_anyone(self):
        self.assertIsNone(vg.infer_seat('in the back of the driving car, standing'))
        self.assertEqual(vg.resolve_body([{'visual_desc': 'a grey sedan parked on a suburban street'}]), 'sedan')

    def test_third_row_seat_dropped_in_two_row_body(self):
        self.assertEqual(vg.occupants(panel([actor('A', 'x', seat='third-left')]), 'lhd', vg.BODIES['suv']), [])
        self.assertFalse(vg.valid_shot('lap-third-left', vg.BODIES['suv']))
        self.assertTrue(vg.valid_shot('lap-third-left', vg.BODIES['suv3']))

    def test_one_person_per_seat(self):
        occ = vg.occupants(panel([actor('A', 'rear-left'), actor('B', 'rear left seat')]), 'lhd', vg.BODIES['suv'])
        self.assertEqual([o.name for o in occ], ['A'])


class MirroringTests(unittest.TestCase):
    """The failure that started this: rear-left rendered on frame-left in a rear-facing shot."""

    def test_rear_facing_two_shot_puts_vehicle_left_on_frame_right(self):
        b = blocking(panel(REAR_PAIR, camera_position='between-front-seats'))
        self.assertEqual(b.shot, 'front-center-back')
        self.assertTrue(place(b, 'Kidnapper')[0].startswith('frame-right'))
        self.assertTrue(place(b, 'Girl')[0].startswith('frame-left'))
        self.assertFalse(place(b, 'Driver')[1])
        self.assertIn("vehicle's left side appears on frame-right", vg.blocking_block(b))

    def test_forward_facing_shots_keep_vehicle_left_on_frame_left(self):
        front = [actor('Driver', 'driver'), actor('Passenger', 'front passenger seat')]
        b = blocking(panel(front, scale='WS', vehicle_shot='rear-center-forward'))
        self.assertTrue(place(b, 'Driver')[0].startswith('frame-left'))
        b = blocking(panel(front, scale='WS', vehicle_shot='windshield-front'))
        self.assertTrue(place(b, 'Driver')[0].startswith('frame-right'))  # facing the car from the hood

    def test_background_names_the_glass_the_camera_faces(self):
        rear = vg.blocking_block(blocking(panel(REAR_PAIR, vehicle_shot='front-center-back')))
        self.assertIn('rear window', rear)
        self.assertIn('windshield and dashboard are behind the camera', rear)
        fwd = vg.blocking_block(blocking(panel(REAR_PAIR, scale='WS', vehicle_shot='rear-center-forward')))
        self.assertIn('Background: the dashboard and the windshield', fwd)
        self.assertIn('Camera outside, in front', vg.blocking_block(blocking(panel(REAR_PAIR, vehicle_shot='windshield-front'))))

    def test_door_side_follows_the_seat(self):
        b = blocking(panel(REAR_PAIR, camera_position='between-front-seats'))
        doors = {o.name: vg._door(b.camera, o, b.body, b.side) for o in b.occupants}
        self.assertIn('frame-right', doors['Kidnapper'])
        self.assertIn('frame-left', doors['Girl'])
        side = blocking(panel(REAR_PAIR, scale='MS', vehicle_shot='side-rear-right'))
        girl = next(o for o in side.occupants if o.name == 'Girl')
        self.assertIn('foreground', vg._door(side.camera, girl, side.body, side.side))

    def test_pov_owner_is_not_drawn(self):
        b = blocking(panel(REAR_PAIR, scale='CU', vehicle_shot='pov:rear-left>rear-right'))
        self.assertIn('camera IS this person', place(b, 'Kidnapper')[0])
        self.assertTrue(place(b, 'Girl')[1])


class ShotChoiceTests(unittest.TestCase):
    def test_explicit_shot_wins_and_invalid_falls_back(self):
        self.assertEqual(blocking(panel(REAR_PAIR, vehicle_shot='mirror-back')).reason, 'vehicle_shot')
        for bad in ('side-rear-center', 'pov:rear-left>rear-left', 'lap-third-left', 'nonsense'):
            self.assertNotEqual(blocking(panel(REAR_PAIR, vehicle_shot=bad)).shot, bad, bad)

    def test_camera_position_keywords(self):
        cases = {
            "from The Girl's POV, looking at The Kidnapper": 'pov:rear-right>rear-left',
            'directly over the smartphone': 'lap-rear-left',
            'rear-view mirror': 'mirror-back',
        }
        for cam, shot in cases.items():
            p = panel([REAR_PAIR[0], {**REAR_PAIR[1], 'in_frame': True}, {**REAR_PAIR[2], 'in_frame': False}],
                      scale='CU', camera_position=cam)
            self.assertEqual(blocking(p).shot, shot, cam)

    def test_single_looking_at_occupant_gets_reverse_over_the_shoulder(self):
        p = panel([REAR_PAIR[0], REAR_PAIR[1], {**REAR_PAIR[2], 'in_frame': False}], scale='CU')
        self.assertEqual(blocking(p).shot, 'ots:rear-right>rear-left')

    def test_unseated_actor_in_frame_cancels_blocking(self):
        # mafia S001_P09: the subject leans out of the open door, only the unframed driver is seated
        p = panel([actor('Girl', 'leaning out of the open rear door'), actor('Driver', "in the driver's seat", in_frame=False)],
                  scale='CU', camera_position='in back seat, next to The Girl')
        self.assertIsNone(blocking(p))
        self.assertIsNone(blocking(panel([{**a, 'in_frame': False} for a in REAR_PAIR], scale='ECU')))

    def test_actor_outside_the_car_does_not_cancel_blocking(self):
        p = panel([*REAR_PAIR, actor('Father', 'on the road far behind the SUV, visible through the rear window')])
        b = blocking(p)
        self.assertIsNotNone(b)
        self.assertNotIn('Father', [o.name for o in b.occupants])

    def test_exterior_panel_keeps_no_blocking(self):
        p = panel(REAR_PAIR, location_references=['Forest-Road-View-Primary'])
        self.assertIsNone(vg.panel_blocking(p, {'location': 'Black-SUV-Interior-To-Entrance'}, {}.get))

    def test_body_from_ref_text_and_explicit_field(self):
        self.assertEqual(vg.resolve_body([SUV]), 'suv')
        self.assertEqual(vg.resolve_body([{'visual_desc': 'a minivan'}]), 'minivan')
        self.assertEqual(vg.resolve_body([{'body': 'suv3', 'visual_desc': 'sedan'}]), 'suv3')
        self.assertEqual(vg.resolve_body([]), 'sedan')

    def test_every_catalog_shot_builds_for_every_aspect(self):
        body = vg.BODIES['suv3']
        for shot in shot_ids('suv3'):
            for aspect in ((9, 16), (16, 9)):
                cam = vg.build_camera(shot, body, 'lhd', 'WS', aspect, 'rear-left')
                self.assertTrue(0 < cam.hfov < 120 and 0 < cam.vfov < 120, (shot, aspect))


class AspectTests(unittest.TestCase):
    def test_wide_mounts_fix_horizontal_fov(self):
        p = panel(REAR_PAIR, scale='WS', vehicle_shot='front-center-back')
        tall, wide = blocking(p, '9:16').camera, blocking(p, '16:9').camera
        self.assertAlmostEqual(tall.hfov, wide.hfov)
        self.assertGreater(tall.vfov, tall.hfov)
        self.assertLess(wide.vfov, wide.hfov)
        # both rear passengers stay in frame either way
        for aspect in ('9:16', '16:9'):
            b = blocking(p, aspect)
            self.assertTrue(place(b, 'Kidnapper')[1] and place(b, 'Girl')[1], aspect)

    def test_tight_scales_fix_short_side(self):
        p = panel(REAR_PAIR, scale='CU', vehicle_shot='ots:rear-left>rear-right')
        tall, wide = blocking(p, '9:16').camera, blocking(p, '16:9').camera
        self.assertAlmostEqual(min(tall.hfov, tall.vfov), min(wide.hfov, wide.vfov))

    def test_sketch_size_follows_aspect(self):
        p = panel(REAR_PAIR, vehicle_shot='mirror-back')
        self.assertEqual((vg.sketch_spec(blocking(p, '9:16'))['width_px'], vg.sketch_spec(blocking(p, '9:16'))['height_px']), (576, 1024))
        self.assertEqual((vg.sketch_spec(blocking(p, '16:9'))['width_px'], vg.sketch_spec(blocking(p, '16:9'))['height_px']), (1024, 576))


class CacheTests(unittest.TestCase):
    def test_sketch_key_is_content_addressed(self):
        ref_dir = Path('/nonexistent')
        a = blocking(panel(REAR_PAIR, vehicle_shot='mirror-back'))
        self.assertEqual(sketch_path(ref_dir, a), sketch_path(ref_dir, blocking(panel(REAR_PAIR, vehicle_shot='mirror-back'))))
        self.assertNotEqual(sketch_path(ref_dir, a), sketch_path(ref_dir, blocking(panel(REAR_PAIR, vehicle_shot='mirror-back'), '16:9')))

    @unittest.skipUnless(get_engine().available(), 'the AI_RENDER3D engine is not installed')
    @pytest.mark.render3d
    def test_engine_renders_and_caches(self):
        b = blocking(panel(REAR_PAIR, vehicle_shot='front-center-back'))
        with tempfile.TemporaryDirectory() as tmp:
            path = render_blockings([b], Path(tmp))[b]
            self.assertGreater(path.stat().st_size, 1000)
            mtime = path.stat().st_mtime_ns
            render_blockings([b], Path(tmp))
            self.assertEqual(path.stat().st_mtime_ns, mtime)


class WiringTests(unittest.TestCase):
    def test_interior_ref_label_is_materials_only(self):
        self.assertIn('materials', _ref_label('Black-SUV-Interior-To-Entrance', 'Vehicle', ''))
        self.assertIn('PROP', _ref_label('Black-SUV-Exterior', 'Vehicle', ''))

    def test_without_sketch_the_block_never_mentions_image_1(self):
        from lib.studio.artist.panels import _panel_blocking_context
        project = SimpleNamespace(character_info={'Black-SUV-Exterior': SUV}, ref_dir=Path('/nonexistent'))
        p = panel(REAR_PAIR, camera_position='between-front-seats')
        with mock.patch('lib.studio.blocking_sketch.panel_sketch', side_effect=AssertionError('rendered')):
            text, sketch = _panel_blocking_context({}, p, project, '9:16', with_sketch=False)
        self.assertIsNone(sketch)
        self.assertNotIn('IMAGE 1', text)
        self.assertNotIn('mannequin', text)

    def test_panel_context_replaces_anchor_block_and_respects_mode(self):
        from lib.studio.artist.panels import _panel_blocking_context
        project = SimpleNamespace(character_info={'Black-SUV-Exterior': SUV}, ref_dir=Path('/nonexistent'))
        p = panel(REAR_PAIR, camera_position='between-front-seats')
        with mock.patch.dict(os.environ, {'AI_BLOCKING': 'text'}):
            text, sketch = _panel_blocking_context({}, p, project, '16:9')
        self.assertIn('VEHICLE BLOCKING', text)
        self.assertIsNone(sketch)
        self.assertNotIn('IMAGE 1', text)
        with mock.patch.dict(os.environ, {'AI_BLOCKING': 'off'}):
            self.assertEqual(_panel_blocking_context({}, p, project, '9:16'), ('', None))
        with mock.patch.dict(os.environ, {'AI_BLOCKING': '', 'AI_CAR_BLOCKING': 'off'}):  # legacy name still read
            self.assertEqual(_panel_blocking_context({}, p, project, '9:16'), ('', None))

    def test_qa_block_uses_judged_image_aspect(self):
        from lib.studio.critic import _blocking_qa_block
        catalog = {'Black-SUV-Exterior': {'json': SUV}}
        p = panel(REAR_PAIR, camera_position='between-front-seats')
        block, replaces_anchors = _blocking_qa_block(p, {}, catalog, (1360, 768))
        self.assertTrue(replaces_anchors)
        self.assertIn("prefix each with 'BLOCKING:'", block)
        self.assertIn('Kidnapper — rear left seat (behind the driver): frame-right', block)
        street = panel(REAR_PAIR, location_references=['Street-View-Primary'])
        self.assertEqual(_blocking_qa_block(street, {}, catalog, (9, 16)), ('', False))


if __name__ == '__main__':
    unittest.main()
