"""Outdoor station rig: four views turning in place at one camera station."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project
from lib.studio.artist import remake_room_refs
from lib.studio.artist.view_geometry import _view_aspect_ratio, view_camera
from lib.studio.room_blocking import blocking_block, panel_blocking
from lib.studio.room_sketch import OUTDOOR_HEIGHT_M, build_sketch_spec
from lib.studio.screenwriter.passes import _counterpart_slugs

# Lexington-like street: View-Primary looks along it (+y), the café facade on its right (x=1), far facades at x=0.
ANCHORS = {'room_m': [20, 40], 'station': [0.6, 0.5], 'objects': [
    {'id': 'cafe-facade', 'label': 'Café facade', 'x': 1.0, 'y': 0.5, 'z': 0.5, 'width_x': 0.02, 'depth_y': 1.0},
    {'id': 'cafe-entrance', 'label': 'Café door', 'x': 1.0, 'y': 0.55, 'z': 0.1, 'width_x': 0.005, 'depth_y': 0.05},
    {'id': 'key-table', 'label': 'Table', 'x': 0.9, 'y': 0.45, 'z': 0.05, 'width_x': 0.04, 'depth_y': 0.02},
    {'id': 'newsstand', 'label': 'Newsstand', 'x': 0.1, 'y': 0.5, 'z': 0.05, 'width_x': 0.05, 'depth_y': 0.05},
], 'zones': []}
REFS = {'Cafe-View-Primary': {'name': 'Cafe-View-Primary', 'type': 'Outdoor', 'anchor_points': ANCHORS}}
VIEWS = ['Cafe-View-Opposite', 'Cafe-View-Ortho-Primary', 'Cafe-View-Ortho-Opposite']


def panel(ref, *actors, scale='WS'):
    return {'panel_index': 1, 'scale': scale, 'location_references': [ref],
            'state': {'actors': [{'name': n, 'position': pos, 'in_frame': True} for n, pos in actors]}}


class StationTests(unittest.TestCase):
    def test_four_headings_share_the_station(self):
        headings = {s: view_camera(s, ANCHORS) for s in ('View-Primary', 'View-Ortho-Primary',
                                                          'View-Opposite', 'View-Ortho-Opposite')}
        self.assertEqual({h[:2] for h in headings.values()}, {(0.6, 0.5)})
        self.assertEqual([h[2:] for h in headings.values()], [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)])

    def test_station_defaults_to_centre_and_ignores_garbage(self):
        self.assertEqual(view_camera('View-Ortho-Primary')[:2], (0.5, 0.5))
        self.assertEqual(view_camera('View-Primary', {'station': [1.4, 'x']})[:2], (0.5, 0.5))
        self.assertNotEqual(view_camera('View-From-Entrance', ANCHORS)[:2], (0.6, 0.5))  # rooms have no station

    def test_ortho_primary_faces_the_cafe_from_the_station(self):
        p = panel('Cafe-View-Ortho-Primary', ('Ann', 'standing at the [cafe-entrance]'), ('Bob', 'seated at the [key-table]'))
        b = panel_blocking(p, None, REFS.get)
        self.assertEqual(b.camera.position[:2], (12.0, 20.0))
        lines = {line.split(' ')[1]: line for line in blocking_block(b).splitlines() if line.startswith('- ')}
        self.assertIn('frame-left', lines['Ann'])   # further along the street (+y) → left when facing +x
        self.assertIn('frame-right', lines['Bob'])

    def test_sketches_stand_at_the_station_with_full_height_facades(self):
        spec = build_sketch_spec(ANCHORS, VIEWS, {})
        for view in spec['views']:
            self.assertEqual(view['position_m'][:2], [12.0, 20.0])
            self.assertNotIn('clip_start_m', view)
        facade = next(o for o in spec['objects'] if o['id'] == 'cafe-facade')
        self.assertEqual(facade['size_m'][2], OUTDOOR_HEIGHT_M)
        door = next(o for o in spec['objects'] if o['id'] == 'cafe-entrance')
        self.assertLess(door['center_m'][0] - door['size_m'][0] / 2,
                        facade['center_m'][0] - facade['size_m'][0] / 2)  # the door stands proud of the facade
        newsstand = next(o for o in spec['objects'] if o['id'] == 'newsstand')
        self.assertLess(newsstand['size_m'][2], 3.0)

    def test_along_views_are_wider_than_across_views_on_a_landscape_plate(self):
        lens = {v['suffix']: v['hfov_degrees'] for v in build_sketch_spec(ANCHORS, VIEWS, {})['views']}
        self.assertGreater(lens['View-Opposite'], lens['View-Ortho-Primary'] + 10)
        self.assertEqual(lens['View-Ortho-Primary'], lens['View-Ortho-Opposite'])
        self.assertEqual(_view_aspect_ratio('View-Ortho-Primary', [20, 40], {}), '16:9')


class CounterpartTests(unittest.TestCase):
    def test_ortho_slugs_only_when_the_location_has_them(self):
        self.assertEqual(_counterpart_slugs(['Cafe-View-Primary'], {}), ['Cafe-View-Opposite'])
        slugs = _counterpart_slugs(['Cafe-View-Primary'], {'Cafe-View-Ortho-Primary': {}, 'Cafe-View-Ortho-Opposite': {}})
        self.assertEqual(slugs, ['Cafe-View-Opposite', 'Cafe-View-Ortho-Primary', 'Cafe-View-Ortho-Opposite'])


class RemakeTests(unittest.TestCase):
    def test_two_view_locations_get_the_missing_station_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp)
            for name in ('Cafe-View-Primary', 'Cafe-View-Opposite'):
                (ref_dir / f'{name.lower()}.json').write_text(json.dumps(
                    {'name': name, 'type': 'Outdoor', 'visual_desc': 'Street.'}))
            project = Project()
            project.ref_dir = ref_dir
            remake_room_refs({}, None, project, create_only=True)
            ortho = json.loads((ref_dir / 'cafe-view-ortho-primary.json').read_text())
            self.assertEqual(ortho['style_reference'], 'Cafe-View-Primary')
            self.assertIn('turned 90 degrees RIGHT', ortho['visual_desc'])
            self.assertTrue((ref_dir / 'cafe-view-ortho-opposite.json').exists())
            self.assertEqual(json.loads((ref_dir / 'cafe-view-opposite.json').read_text())['visual_desc'], 'Street.')

    def test_monolithic_location_splits_into_four_views_sharing_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp)
            (ref_dir / 'park.json').write_text(json.dumps({'name': 'Park', 'type': 'Outdoor', 'visual_desc': 'Park.'}))
            project = Project()
            project.ref_dir = ref_dir
            remake_room_refs({}, None, project, create_only=True)
            refs = {s: json.loads((ref_dir / f'park-view-{s}.json').read_text()).get('style_reference')
                    for s in ('primary', 'opposite', 'ortho-primary', 'ortho-opposite')}
            self.assertEqual(refs, {'primary': '', 'opposite': 'Park-View-Primary',
                                    'ortho-primary': 'Park-View-Primary', 'ortho-opposite': 'Park-View-Primary'})


if __name__ == '__main__':
    unittest.main()
