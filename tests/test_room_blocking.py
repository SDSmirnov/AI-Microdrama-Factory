"""Actor positions from anchors, the panel camera derived from its view, room blocking and the ledger in metres."""
import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import ledger
from lib.studio.positions import match_anchor, resolve
from lib.studio.blocking import equivalent_focal_mm
from lib.studio.positions import Pose
from lib.studio.room_blocking import (
    RoomBlocking, _inside_body, annotate, background_line, blocking_block, panel_blocking, panel_camera,
)

ROOM = 'Cafe-View-From-Entrance'
ANCHORS = {'room_m': [10, 4], 'objects': [
    {'id': 'key-table', 'label': 'Key table', 'x': 0.65, 'y': 0.9, 'z': 0.2, 'width_x': 0.08, 'depth_y': 0.15},
    {'id': 'key-table-chair-street-side', 'label': 'Chair', 'x': 0.65, 'y': 0.75, 'z': 0.1, 'width_x': 0.04, 'depth_y': 0.1},
    {'id': 'key-table-chair-aisle-side', 'label': 'Chair', 'x': 0.55, 'y': 0.9, 'z': 0.1, 'width_x': 0.04, 'depth_y': 0.1},
    {'id': 'long-sofa', 'label': 'Sofa', 'x': 0.2, 'y': 0.5, 'z': 0.1, 'width_x': 0.2, 'depth_y': 0.2},
    {'id': 'entrance-door', 'label': 'Door', 'x': 0.5, 'y': 0.0, 'z': 0.4, 'width_x': 0.1, 'depth_y': 0.0},
    # facing the far wall: a body lying on it extends toward an entrance-side camera
    {'id': 'guest-bed', 'label': 'Bed', 'x': 0.85, 'y': 0.45, 'z': 0.1, 'width_x': 0.15, 'depth_y': 0.4, 'facing_degrees_y': 180},
], 'zones': [{'id': 'window-zone', 'label': 'Window zone', 'x': 0.9, 'y': 0.5}]}
REFS = {ROOM: {'name': ROOM, 'type': 'Room', 'anchor_points': ANCHORS}}


def actor(name, position, in_frame=True, **extra):
    return {'name': name, 'position': position, 'in_frame': in_frame, 'visual_ref': name, **extra}


def panel(*actors, ref=ROOM, scale='WS', **extra):
    return {'panel_index': 1, 'scale': scale, 'location_references': [ref], 'state': {'actors': list(actors)}, **extra}


def metres(pose):
    return pose.metres(ANCHORS['room_m'])


class ResolverTests(unittest.TestCase):
    def test_label_like_brackets_match_ids(self):
        self.assertEqual(match_anchor('chair on street side of key table', ANCHORS)['id'], 'key-table-chair-street-side')
        self.assertEqual(match_anchor('key-table', ANCHORS)['id'], 'key-table')
        self.assertIsNone(match_anchor('grand piano', ANCHORS))

    def test_seated_prefers_the_chair_over_the_table_it_faces(self):
        poses = resolve(panel(actor('Janet', 'Seated at the [key-table], in the [chair on street side of key table].')), ANCHORS)
        self.assertEqual(poses['Janet'].anchor, 'key-table-chair-street-side')
        self.assertEqual(poses['Janet'].posture, 'seated')
        self.assertAlmostEqual(poses['Janet'].x, 0.65, places=2)

    def test_standing_at_furniture_is_outside_its_footprint(self):
        x, y = metres(resolve(panel(actor('Max', 'standing at the [long-sofa]')), ANCHORS)['Max'])
        self.assertFalse(abs(x - 2.0) < 1.0 and abs(y - 2.0) < 0.4)

    def test_people_keep_apart_and_face_who_they_are_opposite(self):
        poses = resolve(panel(actor('Stanton Frelaine', 'Seated in the [chair on aisle side of key table], opposite Janet.'),
                              actor('Janet Patzig', 'Seated in the [chair on street side of key table], opposite Frelaine.')),
                        ANCHORS)
        (sx, sy), (jx, jy) = metres(poses['Stanton Frelaine']), metres(poses['Janet Patzig'])
        self.assertGreaterEqual(math.hypot(sx - jx, sy - jy), 0.45)
        rad = math.radians(poses['Janet Patzig'].facing_deg)
        self.assertGreater(math.sin(rad) * (sx - jx) - math.cos(rad) * (sy - jy), 0)  # Janet faces Stanton

    def test_left_and_right_halves_of_a_sofa(self):
        poses = resolve(panel(actor('A', 'lying on the image-left side of the [long-sofa]'),
                              actor('B', 'lying on the image-right side of the [long-sofa]')), ANCHORS)
        self.assertLess(poses['A'].x, poses['B'].x)

    def test_unknown_place_is_left_out_not_guessed(self):
        self.assertEqual(resolve(panel(actor('Stanton', 'inside a phone booth across town')), ANCHORS), {})

    def test_placement_wins_over_text(self):
        a = actor('Max', 'standing at the [long-sofa]',
                  placement={'anchor': 'window-zone', 'relation': 'at', 'target': '', 'distance_m': 0, 'posture': 'standing'})
        pose = resolve(panel(a), ANCHORS)['Max']
        self.assertEqual((pose.anchor, pose.source), ('window-zone', 'placement'))


class VehicleOccupantTests(unittest.TestCase):
    """Sevens S1: 'In a stationary taxi on the street, adjacent to the [street-curb]' put Stanton on the curb."""

    def test_someone_inside_a_vehicle_gets_no_room_position(self):
        poses = resolve(panel(actor('Stanton', 'In a stationary taxi on the street, adjacent to the [entrance-door].'),
                              actor('Kid', 'at the [long-sofa]', vehicle_position='rear-left'),
                              actor('Max', 'standing by the taxi at the [entrance-door]')), ANCHORS)
        self.assertEqual(sorted(poses), ['Max'])


class CameraTests(unittest.TestCase):
    def test_wide_shot_steps_past_someone_at_the_lens(self):
        door = {'anchor': 'entrance-door', 'relation': 'in-front-of', 'target': '', 'distance_m': 0.6, 'posture': 'standing'}
        p = panel(actor('Max', '', placement=door), camera_x=0.5, camera_y=0.075)  # camera 0.3 m into the room
        b = panel_blocking(p, None, REFS.get)
        (cx, cy, cz), (mx, my) = b.camera.position, metres(b.poses['Max'])
        ahead, side = my - cy, mx - cx  # entrance view looks along +y
        self.assertFalse(0 < ahead < 0.5 and abs(side) < 0.35, (cx, cy, mx, my))
        self.assertFalse(_inside_body((cx, cy, cz), b.poses['Max'], ANCHORS['room_m']))

    def test_named_camera_is_the_story_camera(self):
        # Sevens P1: 'inside taxi at street-curb', MS of Janet at her table
        p = panel(actor('Janet', 'Seated in the [chair on street side of key table]'), scale='MS',
                  camera_position='inside taxi at entrance-door')
        b = panel_blocking(p, None, REFS.get)
        cx, cy, cz = b.camera.position
        self.assertLess(math.hypot(cx - 5.0, cy - 0.0), 0.6)  # at the door, stepped toward her
        self.assertEqual(cz, 1.2)  # seated in the taxi
        self.assertGreater(equivalent_focal_mm(b.camera), 70)  # a long lens instead of a dolly

    def test_named_camera_too_far_for_the_shot_falls_back(self):
        # Billionaire P6: 'near display-shelving-wall' is just the nearest landmark; a CU from there needs ~170 mm
        p = panel(actor('Janet', 'Seated in the [chair on street side of key table]'), scale='CU',
                  camera_position='near entrance-door')  # in the view's direction, but ~3 m away
        b = panel_blocking(p, None, REFS.get)
        self.assertLessEqual(equivalent_focal_mm(b.camera), 100)
        self.assertLess(math.dist(b.camera.position[:2], metres(b.poses['Janet'])), 1.5)

    def _ots(self, ann_x):
        """Max at the room centre, Ann 0.4 m toward the entrance camera and slightly to one side (Billionaire P6)."""
        poses = {'Ann': Pose(ann_x, 0.4, 180, 'standing', None, 'placement'),
                 'Max': Pose(0.5, 0.5, 0, 'standing', None, 'placement')}
        p = panel(actor('Ann', ''), actor('Max', ''), scale='CU', drama_requirements={'focus_priority': {'primary_target': 'Max'}})
        camera, _, cut, ots = panel_camera(p, 'View-From-Entrance', poses, (10, 4), 3.0, (9, 16), ANCHORS)
        b = RoomBlocking('Cafe', 'View-From-Entrance', camera, poses, (10, 4), 3.0, ANCHORS, None, (9, 16), cut, ots)
        return b, {line.split(' ')[1]: line for line in blocking_block(b).splitlines() if line.startswith('- ')}

    def test_partner_beside_the_subject_frames_an_over_the_shoulder(self):
        b, lines = self._ots(0.48)
        self.assertEqual(b.ots, 'Ann')
        self.assertIn('over-the-shoulder', lines['Ann'])
        self.assertIn('frame-center', lines['Max'])
        self.assertFalse(any(_inside_body(b.camera.position, pose, (10, 4)) for pose in b.poses.values()))

    def test_over_the_shoulder_keeps_the_partners_side(self):
        for ann_x, side in ((0.48, 'frame-left'), (0.52, 'frame-right')):  # entrance view: image-left is x < 0.5
            b, lines = self._ots(ann_x)
            self.assertEqual(b.ots, 'Ann')
            self.assertIn(side, lines['Ann'], ann_x)

    def test_group_medium_shot_frames_the_people_not_the_room(self):
        # Billionaire P8: the couple 10 m away from the far-end view; now framed
        p = panel(actor('Ann', 'standing at the [entrance-door]'), actor('Max', 'standing at the [entrance-door]'),
                  ref='Cafe-View-To-Entrance', scale='MS')
        b = panel_blocking(p, None, REFS.get)
        for name in ('Ann', 'Max'):
            self.assertLess(math.dist(b.camera.position[:2], metres(b.poses[name])), 4.0)
            self.assertNotIn('do not draw', next(line for line in blocking_block(b).splitlines() if line.startswith(f'- {name}')))

    def test_extreme_close_up_gets_the_block_but_no_sketch(self):
        from types import SimpleNamespace
        from unittest import mock

        from lib.studio.artist.panels import _panel_blocking_context
        project = SimpleNamespace(character_info=REFS, character_images={}, ref_dir=Path('/nonexistent'))
        with mock.patch('lib.studio.blocking_sketch.panel_sketch', side_effect=AssertionError('sketch requested')):
            text, sketch = _panel_blocking_context({}, panel(actor('Max', 'at the [long-sofa]'), scale='ECU'), project, '9:16')
        self.assertIsNone(sketch)
        self.assertIn('ROOM BLOCKING', text)
        self.assertNotIn('IMAGE 1', text)

    def test_contradicting_llm_camera_is_replaced_on_wide_shots_only(self):
        p = panel(actor('Max', 'at the [long-sofa]'), camera_x=0.95, camera_y=0.95)
        self.assertIn('contradict', panel_blocking(p, None, REFS.get).note)
        self.assertIsNone(panel_blocking({**p, 'scale': 'CU'}, None, REFS.get).note)

    def test_close_up_dollies_in_along_the_view_axis(self):
        b = panel_blocking(panel(actor('Max', 'standing at the [long-sofa]'), scale='CU'), None, REFS.get)
        (px, py, _), (tx, ty, _) = b.camera.position, b.camera.target
        self.assertAlmostEqual(px, tx, places=6)  # entrance view looks along +y
        self.assertTrue(0.5 < ty - py < 1.0)
        self.assertIn('frame-center, foreground', blocking_block(b))

    def test_close_up_camera_never_inside_a_lying_body(self):
        b = panel_blocking(panel(actor('Alisa', 'lying on the [guest-bed]'), scale='CU'), None, REFS.get)
        pose, (x, y, z) = b.poses['Alisa'], b.camera.position
        self.assertTrue(_inside_body((x, y, 0.35), pose, ANCHORS['room_m']))  # at head height: the old bug
        self.assertFalse(_inside_body((x, y, z), pose, ANCHORS['room_m']))

    def test_annotate_is_idempotent(self):
        scenes = [{'scene_id': 1, 'panels': [panel(actor('Max', 'at the [long-sofa]'), camera_x=0.95, camera_y=0.95)]}]
        first = annotate(scenes, REFS.get)
        again = annotate(copy.deepcopy(scenes), REFS.get)
        self.assertEqual((first['placed'], len(first['camera_fixed'])), (1, 1))
        self.assertEqual(len(again['camera_fixed']), 0)
        self.assertIn('x_m', scenes[0]['panels'][0]['state']['actors'][0]['pos'])

    def test_no_anchors_no_blocking(self):
        self.assertIsNone(panel_blocking(panel(actor('Max', 'at [x]'), ref='Street-View-Primary'), None, REFS.get))


class LedgerMetricTests(unittest.TestCase):
    def test_moves_are_measured_in_metres_once_positions_exist(self):
        scene = {'scene_id': 1, 'panels': [
            {**panel(actor('Max', 'at the [long-sofa]')), 'panel_index': 1},
            {**panel(actor('Max', 'at the [window-zone]')), 'panel_index': 2},
        ]}
        annotate([scene], REFS.get)
        issues = ledger.check([scene])
        self.assertEqual(len(issues), 1)
        self.assertRegex(issues[0].message, r'moves \d+\.\d m')
        scene['panels'][1]['state']['actors'][0]['motion_action'] = 'walks to the window'
        self.assertEqual(ledger.check([scene]), [])


class BackgroundWallTests(unittest.TestCase):
    def _line(self, view, position, scale='CU'):
        p = panel(actor('Janet', position), ref=f'Cafe-{view}', scale=scale)
        return background_line(panel_blocking(p, None, REFS.get))

    def test_entrance_camera_sees_the_far_wall_behind_a_far_table(self):
        line = self._line('View-From-Entrance', 'Seated in the [chair on street side of key table].')
        self.assertIn('far wall', line)
        self.assertIn('[key-table]', line)

    def test_reverse_camera_sees_the_entrance_wall_and_door(self):
        line = self._line('View-To-Entrance', 'Standing by the [entrance-door].', scale='MS')
        self.assertIn('entrance wall', line)
        self.assertIn('[entrance-door]', line)

    def test_line_goes_into_the_blocking_block(self):
        b = panel_blocking(panel(actor('Janet', 'Seated in the [chair on street side of key table].'), scale='CU'),
                           None, REFS.get)
        self.assertIn(background_line(b), blocking_block(b))


if __name__ == '__main__':
    unittest.main()
