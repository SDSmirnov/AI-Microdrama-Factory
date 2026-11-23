"""render3d: engine-neutral scenes, the factory, the Blender engine's failure path, room-view metadata."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import vehicle_geometry as vg
from lib.studio.render3d import shapes
from lib.studio.render3d.engines.blender import BlenderEngine
from lib.studio.render3d.factory import get_engine
from lib.studio.room_sketch import _view_meta, build_sketch_spec

ANCHORS = {'room_m': [6, 5], 'objects': [
    {'id': 'dining-table', 'label': 'Dining table', 'x': 0.5, 'y': 0.6, 'z': 0.2, 'width_x': 0.3, 'depth_y': 0.2},
    {'id': 'tall-cabinet', 'label': 'Tall cabinet', 'x': 0.1, 'y': 0.9, 'z': 0.5, 'width_x': 0.1, 'depth_y': 0.1},
]}


def view(position, target, **extra):
    return {'name': 'v', 'suffix': 'View-From-Entrance', 'position_m': position, 'target_m': target,
            'forward': [0, 1], 'hfov_degrees': 60, 'width_px': 576, 'height_px': 1024, **extra}


def car_job(shot='front-center-back'):
    body = vg.BODIES['suv']
    occ = (vg.Occupant('Kid', 'rear-left', 'red', '#d62828', 'rear-right'), vg.Occupant('Girl', 'rear-right', 'blue', '#1d6fd6'))
    cam = vg.build_camera(shot, body, 'lhd', 'WS', (9, 16), 'rear-left')
    return vg.sketch_spec(vg.Blocking('SUV', 'suv', 'lhd', shot, 't', cam, occ, (9, 16)))


class SceneTests(unittest.TestCase):
    def test_car_scene_has_cabin_and_one_mannequin_per_occupant(self):
        scene = shapes.car_scene(car_job())
        heads = [m for m in scene.meshes if m.name.endswith('-head')]
        self.assertEqual(sorted(m.name for m in heads), ['rear-left-head', 'rear-right-head'])
        self.assertTrue(any(m.name == 'steering-wheel' for m in scene.meshes))
        self.assertEqual((scene.view.width_px, scene.view.height_px, scene.view.clip_start), (576, 1024, 0.04))
        json.dumps(scene.to_dict())

    def test_pov_owner_gets_no_mannequin(self):
        names = {m.name for m in shapes.car_scene(car_job('pov:rear-left>rear-right')).meshes}
        self.assertNotIn('rear-left-head', names)
        self.assertIn('rear-right-head', names)

    def test_meshes_are_world_space(self):
        job = car_job()
        head = next(m for m in shapes.car_scene(job).meshes if m.name == 'rear-left-head')
        centre = [sum(v[i] for v in head.verts) / len(head.verts) for i in range(3)]
        for got, want in zip(centre, job['occupants'][0]['head']):
            self.assertAlmostEqual(got, want, places=6)

    def test_room_views_cull_per_camera_and_add_their_mannequins(self):
        spec = build_sketch_spec(ANCHORS, [], {})
        actor = {'id': 'ann', 'color': [1, 0, 0], 'hip': [3, 2], 'head': [3, 2, 1.6], 'yaw_pitch': [0, 0],
                 'body_yaw': 0, 'posture': 'standing'}
        spec['views'] = [view([3, 0.3, 1.5], [3, 5, 1.5], culled_ids=['dining-table'], mannequins=[actor]),
                         view([0.6, 4.5, 1.0], [3, 0, 1.0])]  # inside the cabinet's footprint and height
        first, second = shapes.room_scenes(spec)
        groups = lambda s: {m.group for m in s.meshes}  # noqa: E731
        self.assertNotIn('dining-table', groups(first))
        self.assertIn('tall-cabinet', groups(first))
        self.assertIn('dining-table', groups(second))
        self.assertNotIn('tall-cabinet', groups(second))
        self.assertTrue(any(m.name.startswith('ann-') for m in first.meshes))
        self.assertFalse(any(m.name.startswith('ann-') for m in second.meshes))


class MetaTests(unittest.TestCase):
    def test_side_depth_and_culling(self):
        spec = build_sketch_spec(ANCHORS, [], {})
        spec['views'] = [view([3, 0.3, 1.5], [3, 5, 1.5], culled_ids=['tall-cabinet'])]
        meta = _view_meta(spec)['v']
        self.assertTrue(meta['dining-table']['in_front'] and meta['dining-table']['visible'])
        self.assertAlmostEqual(meta['dining-table']['img_x'], 0.5, places=6)
        self.assertFalse(meta['tall-cabinet']['in_front'])
        spec['views'] = [view([3, 4.9, 1.5], [3, 5.9, 1.5])]  # looking at the far wall: the table is behind
        self.assertFalse(_view_meta(spec)['v']['dining-table']['in_front'])


class EngineTests(unittest.TestCase):
    def test_factory(self):
        self.assertEqual(get_engine().name, 'blender')
        with mock.patch.dict(os.environ, {'AI_RENDER3D': 'nonsense'}):
            with self.assertRaises(ValueError):
                get_engine()

    def test_missing_blender_raises_and_reports_unavailable(self):
        engine = BlenderEngine('no-such-blender-binary')
        self.assertFalse(engine.available())
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            engine.render([(shapes.car_scene(car_job()), Path(tmp) / 'x.png')])

    def test_empty_batch_is_a_no_op(self):
        BlenderEngine('no-such-blender-binary').render([])  # would raise if it tried to start Blender


def _has_pyvista():
    try:
        import pyvista  # noqa: F401
    except ImportError:
        return False
    return True


class PyVistaEngineTests(unittest.TestCase):
    def test_auto_prefers_pyvista_and_falls_back_to_blender(self):
        from lib.studio.render3d.engines.pyvista import PyVistaEngine
        with mock.patch.object(PyVistaEngine, 'available', return_value=True):
            self.assertEqual(get_engine('auto').name, 'pyvista')
        with mock.patch.object(PyVistaEngine, 'available', return_value=False):
            self.assertEqual(get_engine('auto').name, 'blender')
        self.assertEqual(get_engine('pyvista').name, 'pyvista')

    def test_lights_follow_the_outdoor_flag(self):
        from lib.studio.render3d.engines import pyvista as eng
        self.assertEqual(len(eng.LIGHTS['outdoor'][1]), 2)  # key + fill sun, unshadowed
        self.assertEqual(len(eng.LIGHTS['enclosed'][1]), 1)  # walls shadow the key sun
        self.assertGreater(eng.LIGHTS['enclosed'][0], eng.LIGHTS['outdoor'][0])

    @unittest.skipUnless(_has_pyvista(), 'pyvista not installed')
    @pytest.mark.pyvista
    def test_renders_headless_at_the_view_size(self):
        from PIL import Image

        from lib.studio.render3d.engines.pyvista import PyVistaEngine
        scene = shapes.car_scene(car_job())
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'DISPLAY': '', 'WAYLAND_DISPLAY': ''}):
            out = Path(tmp) / 'car.png'
            PyVistaEngine().render([(scene, out)])
            with Image.open(out) as img:
                self.assertEqual(img.size, (scene.view.width_px, scene.view.height_px))
                self.assertGreater(len(set(img.convert('L').getdata())), 20)  # drawn, not a blank frame

    def test_sketch_cache_key_names_the_engine(self):
        from lib.studio.blocking_sketch import sketch_path
        b = vg.Blocking('SUV', 'suv', 'lhd', 'mirror-back', 't',
                        vg.build_camera('mirror-back', vg.BODIES['suv'], 'lhd', 'WS', (9, 16)),
                        (vg.Occupant('A', 'driver'),), (9, 16))
        paths = set()
        for engine in ('blender', 'pyvista'):
            with mock.patch.dict(os.environ, {'AI_RENDER3D': engine}):
                paths.add(sketch_path(Path('/x'), b))
        self.assertEqual(len(paths), 2)


if __name__ == '__main__':
    unittest.main()
