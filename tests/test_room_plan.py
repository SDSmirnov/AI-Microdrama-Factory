"""Floor plan first: checked VFE anchors from the description, then VFE renders and is judged against their sketch."""
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project
from lib.studio import artist, room_qa
from lib.studio.artist.view_geometry import _view_rig
from lib.studio.room_geometry import WALL_INSET_M
from lib.studio.room_plan import run_room_plans, validate_plan
from lib.studio.room_sketch import _view_meta, build_sketch_spec

W, D = 3.0, 3.5  # the Chiomonte grocery: crates left, counter right with the shopkeeper's aisle behind it


def obj(id, label, x0, x1, y0, y1, h=None, z=0.1, facing=-1, **kw):
    o = dict(id=id, label=label, x=(x0 + x1) / 2 / W, y=(y0 + y1) / 2 / D, z=z,
             width_x=(x1 - x0) / W, depth_y=(y1 - y0) / D, facing_degrees_y=facing, **kw)
    return {**o, 'height_m': h} if h else o


def grocery(shelf_end=1.65):
    return {'room_m': [W, D], 'room_height_m': 2.6, 'objects': [
        obj('shop-entrance-doorway', 'Entrance doorway', 1.05, 1.95, 0, 0, h=2.0, z=0.38, hinge_side='x0', opens='inward'),
        obj('frosted-side-window', 'Frosted window', 0.05, 0.65, 0, 0, h=0.6, z=0.58),
        obj('produce-crates-stack', 'Produce crates', 0.0, 0.5, 0.5, 2.3, h=0.7, facing=90),
        obj('grocery-counter', 'Grocery counter', 1.7, 2.3, 1.5, 3.3, h=0.95, facing=270),
        obj('far-wall-shelving', 'Far wall shelving', 0.0, shelf_end, 3.15, 3.5, h=2.6, facing=0),
        obj('back-room-curtained-doorway', 'Curtained doorway', 2.2, 2.95, 3.5, 3.5, h=1.9, z=0.37),
    ], 'zones': [
        {'id': 'birbante-doorway-watch-spot', 'label': 'watch spot', 'x': 1.5 / W, 'y': 0.5 / D},
        {'id': 'shopkeeper-behind-counter', 'label': 'shopkeeper', 'x': 2.65 / W, 'y': 2.4 / D},
        {'id': 'shop-centre-floor', 'label': 'centre', 'x': 1.1 / W, 'y': 1.6 / D},
    ]}


VOCABULARY = [{'id': i, 'description': ''} for i in (
    'shop-entrance-doorway', 'grocery-counter', 'shopkeeper-behind-counter', 'far-wall-shelving')]
VFE = 'Grocery-View-From-Entrance'


def issues(plan, vocabulary=VOCABULARY):
    return validate_plan(plan, build_sketch_spec(plan, [VFE], {}), vocabulary)


class ValidateTests(unittest.TestCase):
    def test_a_consistent_layout_passes(self):
        self.assertEqual(issues(grocery()), [])

    def test_the_descriptions_own_clash_is_reported_with_both_ids_and_metres(self):
        # As written: shelving "to ~0.85 m before the right corner" runs into the counter's far end.
        [issue] = issues(grocery(shelf_end=2.15))
        self.assertIn('grocery-counter and far-wall-shelving occupy the same floor: 0.45 x 0.15 m', issue)

    def test_a_crate_closing_the_aisle_strands_the_shopkeeper(self):
        plan = grocery()
        plan['objects'].append(obj('flour-sacks', 'Sack pile', 2.3, 3.0, 1.0, 1.4, h=0.8))
        self.assertEqual(issues(plan), ['no walkable path (0.4 m wide) from shop-entrance-doorway to: '
                                        'shopkeeper-behind-counter, back-room-curtained-doorway'])

    def test_chairs_may_tuck_under_tables(self):
        plan = grocery()
        plan['objects'] += [obj('cafe-table', 'Table', 0.9, 1.5, 2.4, 2.9, h=0.75),
                            obj('cafe-chair', 'Chair', 1.0, 1.4, 2.7, 3.05, h=0.9)]
        self.assertEqual(issues(plan), [])

    def test_openings_off_walls_outside_the_room_and_missing_ids(self):
        plan = grocery()
        plan['objects'][1].update(x=0.5, y=0.3)                # window floating 1 m into the room
        plan['objects'][2]['x'] = 0.0                          # crates half through the left wall
        found = issues(plan, VOCABULARY + [{'id': 'cured-goods-rail'}])
        self.assertEqual(len(found), 3, found)
        self.assertIn('named positions missing from objects and zones: cured-goods-rail', found[0])
        self.assertIn('produce-crates-stack extends outside', found[1])
        self.assertIn('frosted-side-window (window) stands 1.05 m from the nearest wall', found[2])

    def test_openings_straddle_their_wall(self):
        plan = grocery()
        plan['objects'][0]['depth_y'] = 0.1 / D   # door frame 10 cm deep, centred on the entrance wall line
        plan['objects'][1]['depth_y'] = 0.12 / D
        self.assertEqual(issues(plan), [])

    def test_garbage_numbers_are_reported_not_raised(self):
        plan = grocery()
        plan['objects'][2].update(x=None, width_x='wide')
        plan['zones'][0]['x'] = None
        self.assertIsInstance(issues(plan), list)

    # A weaker model's wine shop: spots as objects, no sizes, the storeroom doorway on the corner, zones on furniture.
    def test_standing_spots_written_as_objects_are_sent_to_zones_not_drawn(self):
        plan = grocery()
        plan['objects'] += [dict(id=i, label=i, x=x / W, y=y / D, z=0, width_x=0, depth_y=0) for i, x, y in (
            ('old-men-card-table-spot', 1.1, 1.6), ('barman-behind-counter-spot', 2.65, 2.4))]
        self.assertEqual(issues(plan), ['standing spots listed as objects, move them to zones: '
                                        'old-men-card-table-spot, barman-behind-counter-spot'])

    def test_furniture_without_a_size_is_sent_back(self):
        plan = grocery()
        del plan['objects'][3]['height_m']
        plan['objects'][2]['depth_y'] = 0
        self.assertIn('no real size (width_x, depth_y, height_m): produce-crates-stack, grocery-counter', issues(plan))

    def test_a_token_footprint_is_no_size(self):
        plan = grocery()  # the wine shop's "room" anchor shrunk to 4 x 5 cm, drawn as a 1.2 x 0.8 m default
        plan['objects'].append(obj('tiny-shop-shell', 'Room shell', 1.48, 1.52, 1.7, 1.75, h=2.6, z=0.5))
        self.assertIn('no real size (width_x, depth_y, height_m): tiny-shop-shell', issues(plan))

    def test_a_leafless_passage_is_a_door_and_may_not_sit_on_a_corner(self):
        plan = grocery()
        plan['objects'][5] = dict(id='storeroom-passage', label='storeroom-passage', x=1.0, y=1.0, z=0.37,
                                  width_x=0.75 / W, depth_y=0, height_m=1.9, opens='none')
        spec = build_sketch_spec(plan, [VFE], {})
        self.assertEqual({o['id']: o['category'] for o in spec['objects']}['storeroom-passage'], 'door')
        self.assertEqual(validate_plan(plan, spec, VOCABULARY),
                         ['storeroom-passage (door) runs past the corner of the right wall (3.12–3.88 m along a 3.5 m wall)'])

    def test_a_zone_on_furniture_names_it(self):
        plan = grocery()
        plan['zones'].append({'id': 'counter-zone', 'x': 2.0 / W, 'y': 2.4 / D})
        self.assertEqual(issues(plan), ['zones stand on furniture, move each to the free floor beside it: '
                                        'counter-zone (inside grocery-counter)'])

    def test_a_zone_on_the_reachable_edge_of_furniture_is_still_on_it(self):
        plan = grocery()
        plan['zones'].append({'id': 'counter-front-zone', 'x': 1.75 / W, 'y': 2.4 / D})  # 5 cm inside the front
        self.assertEqual(issues(plan), ['zones stand on furniture, move each to the free floor beside it: '
                                        'counter-front-zone (inside grocery-counter)'])

    def test_room_wide_entries_need_no_anchor(self):
        wide = [{'id': 'gloomy-interior', 'kind': 'room-wide'}, {'id': 'tiny-shop-shell', 'kind': 'room-wide'}]
        self.assertEqual(issues(grocery(), VOCABULARY + wide), [])
        self.assertEqual(issues(grocery(), VOCABULARY + [{'id': 'cured-goods-rail', 'kind': 'object'}]),
                         ['named positions missing from objects and zones: cured-goods-rail'])

    def test_a_counter_too_close_to_the_wall_leaves_no_standing_room_behind_it(self):
        plan = grocery()
        plan['objects'][3].update(x=(1.7 + 2.55) / 2 / W, width_x=0.85 / W)  # aisle 0.70 -> 0.45 m: walkable, not workable
        self.assertEqual(issues(plan), ['shopkeeper-behind-counter has 0.45 m of floor between grocery-counter and '
                                        'right wall; a person needs 0.6 m'])

    def test_no_entrance_door(self):
        plan = grocery()
        plan['objects'][0]['y'] = 1.0  # the doorway moved to the far wall
        self.assertIn('no door on the entrance wall', issues(plan)[-1])


class VfeRigTests(unittest.TestCase):
    def test_vfe_is_a_90_degree_master_from_the_doorway(self):
        self.assertEqual(_view_rig('View-From-Entrance', [W, D], 2.6), (90.0, WALL_INSET_M))
        spec = build_sketch_spec(grocery(), [VFE], {})
        self.assertLess(spec['views'][0]['position_m'][1], 0.1)
        meta = _view_meta(spec)[VFE]
        self.assertTrue(meta['produce-crates-stack']['visible'])  # 42° off-axis: a 55° lens loses it
        self.assertLess(meta['produce-crates-stack']['img_x'], 0.5)


class PlanLLM:
    def __init__(self, plans):
        self.plans, self.prompts = list(plans), []

    def make_json(self, prompt, schema=None):
        self.prompts.append(prompt)
        return self.plans.pop(0)


class RunPlansTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir
        self.json = self.ref_dir / 'grocery-view-from-entrance.json'
        self.json.write_text(json.dumps({'name': VFE, 'type': 'Room', 'room_vocabulary': VOCABULARY,
                                         'visual_desc': 'ROOM SIZE: 3 m wide x 3.5 m deep, 2.6 m ceiling.'}))
        (self.ref_dir / 'grocery-view-from-entrance.png').write_bytes(b'old')

    def plan(self, plans, **kw):
        llm = PlanLLM([{**p, 'zones': p['zones'] or [{}]} for p in plans])
        return run_room_plans(self.project, llm, {}, **kw), llm

    def test_a_failed_check_is_fed_back_and_the_fixed_plan_saved(self):
        summary, llm = self.plan([grocery(2.15), grocery()])
        self.assertEqual(summary['planned'], ['Grocery'])
        self.assertIn('[shopkeeper-behind-counter]', llm.prompts[0])
        self.assertNotIn('FAILED THESE CHECKS', llm.prompts[0])
        self.assertIn('FAILED THESE CHECKS', llm.prompts[1])
        previous = llm.prompts[1].split('YOUR PREVIOUS LAYOUT:\n', 1)[1].split('\n', 1)[0]
        self.assertEqual(json.loads(previous)['objects'], grocery(2.15)['objects'])  # the model edits what it sent
        self.assertIn('grocery-counter and far-wall-shelving occupy the same floor', llm.prompts[1])
        data = json.loads(self.json.read_text())
        self.assertEqual(data['anchor_points']['objects'], grocery()['objects'])
        self.assertEqual(data['floor_plan']['issues'], [])
        self.assertTrue(data['needs_regenerate'])  # the old image predates its layout
        self.assertTrue((self.ref_dir / 'grocery-view-from-entrance.plan.png').exists())

    def test_the_least_broken_plan_is_kept_with_its_issues(self):
        closed = grocery()
        closed['objects'].append(obj('flour-sacks', 'Sack pile', 2.3, 3.0, 1.0, 1.4, h=0.8))
        both = copy.deepcopy(closed)
        both['objects'][4] = grocery(2.15)['objects'][4]
        summary, _ = self.plan([closed, both])  # the retry is worse: keep the first
        self.assertEqual(json.loads(self.json.read_text())['anchor_points']['objects'], closed['objects'])
        self.assertEqual(len(summary['with_issues']['Grocery']), 1)

    def test_anchored_rooms_are_kept_unless_forced(self):
        data = json.loads(self.json.read_text())
        self.json.write_text(json.dumps({**data, 'anchor_points': {'room_m': [1, 1]}}))
        summary, llm = self.plan([])
        self.assertEqual((summary['skipped'], llm.prompts), (['Grocery'], []))
        summary, llm = self.plan([grocery()], force=True)
        self.assertEqual(summary['planned'], ['Grocery'])


def _png(colour=(90, 90, 90), size=(32, 32)):
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, format='PNG')
    return buf.getvalue()


class PlannedChainTests(unittest.TestCase):
    """room-views on a planned room: sketch first, VFE rendered from it and judged against it, plan kept."""

    class ChainLLM:
        def __init__(self):
            self.renders, self.judged = [], []

        def make_image(self, prompt, refs=None, **kwargs):
            self.renders.append((prompt, [getattr(r, 'filename', r) for r in refs or []]))
            return _png()

        def analyze_image(self, image, prompt, schema=None):
            self.judged.append((prompt, [type(i).__name__ if not isinstance(i, str) else i for i in image]))
            return {'style_score': 10, 'architecture_score': 10, 'geometry_score': 10, 'issues': [],
                    'regeneration_prompt': '', 'edit_instructions': [], 'edit_prompt': ''}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir
        self.plan = grocery()
        for suffix, extra in (('View-From-Entrance', {'anchor_points': self.plan, 'floor_plan': {'issues': []}}),
                              ('View-To-Entrance', {})):
            (self.ref_dir / f'grocery-{suffix.lower()}.json').write_text(json.dumps(
                {'name': f'Grocery-{suffix}', 'type': 'Room', 'visual_desc': 'Grocery.', **extra}))
        (self.ref_dir / 'grocery-view-from-entrance.png').write_bytes(_png((1, 1, 1)))

    def fake_render(self, spec_path, meta_path, blender_cmd):
        for out in json.loads(Path(spec_path).read_text())['outputs']:
            Path(out).write_bytes(_png((200, 200, 200)))
        meta_path.write_text('{}')

    def test_vfe_renders_from_its_plan_sketch_and_keeps_the_plan(self):
        llm = self.ChainLLM()
        with mock.patch('lib.studio.room_sketch._render_views', self.fake_render), \
                mock.patch('lib.studio.artist.run_room_anchors') as anchors:
            room_qa.run_room_views(self.project, llm, {}, rooms=['Grocery'], pass_threshold=9, max_attempts=1)
        sketch = str(self.ref_dir / 'grocery-view-from-entrance.sketch.png')
        prompt, refs = llm.renders[0]                       # the new sketch made the old VFE stale
        self.assertEqual(refs[0], sketch)
        self.assertIn('FLOOR-PLAN SKETCH', refs[1])
        self.assertIn('GEOMETRY CONTRACT', prompt)
        vfe_prompt, vfe_images = llm.judged[0]
        self.assertIn('FLOOR-PLAN SKETCH of the same camera comes first', vfe_prompt)
        self.assertEqual(vfe_images[:2], ['# FLOOR-PLAN SKETCH (geometry truth for this camera)\n', 'Image'])
        data = json.loads((self.ref_dir / 'grocery-view-from-entrance.json').read_text())
        self.assertEqual(data['anchor_points'], self.plan)  # a new VFE image does not void its own plan
        anchors.assert_called()

    def test_unplanned_vfe_gets_no_sketch_and_loses_image_anchors(self):
        path = self.ref_dir / 'grocery-view-from-entrance.json'
        data = json.loads(path.read_text())
        data.pop('floor_plan')
        path.write_text(json.dumps(data))
        (self.ref_dir / 'grocery-view-from-entrance.sketch.png').write_bytes(_png())
        llm = self.ChainLLM()
        artist._render_single_ref(data, {}, self.project, llm, force=True)
        self.assertEqual(llm.renders[0][1], [])
        room_qa._vfe_changed(self.project, 'Grocery', path)
        self.assertNotIn('anchor_points', json.loads(path.read_text()))


class SketchRuleTests(unittest.TestCase):
    def test_hanging_strings_are_props_and_a_wall_shelf_hangs(self):
        plan = {'room_m': [W, D], 'room_height_m': 2.6, 'objects': [
            obj('pepper-strings-curtain', 'Pepper strings', 1.05, 1.95, 0, 0.02, h=1.2, z=0.6),
            obj('narrow-wall-shelf', 'Narrow wall shelf', 2.85, 3.0, 2.0, 2.8, h=0.05, z=0.65),
            obj('back-bar-bottle-shelves', 'Three wall shelves', 2.85, 3.0, 0.8, 1.6, h=0.9, z=0.6),
            obj('tall-shelf', 'Shelf unit', 0.0, 0.4, 1.0, 2.0, h=1.8, z=0.5)]}
        objs = {o['id']: o for o in build_sketch_spec(plan, [VFE], {})['objects']}
        self.assertNotIn('pepper-strings-curtain', objs)
        self.assertAlmostEqual(objs['narrow-wall-shelf']['center_m'][2], 0.65 * 2.6, places=2)
        self.assertAlmostEqual(objs['back-bar-bottle-shelves']['center_m'][2], 0.6 * 2.6, places=2)
        self.assertAlmostEqual(objs['tall-shelf']['center_m'][2], 0.9, places=2)



class DoorTests(unittest.TestCase):
    """Mechanism and state reach the sketch: the leaf stands where the door's swing puts it, or nowhere."""

    @staticmethod
    def door_room(**door):
        base = {'id': 'door', 'label': 'Door', 'x': 0.5, 'y': 1.0, 'z': 0.38, 'width_x': 0.9 / W, 'depth_y': 0,
                'height_m': 2.0, 'facing_degrees_y': 0, 'hinge_side': 'x1'}
        return {'room_m': [W, D], 'room_height_m': 2.6, 'objects': [{**base, **door}], 'zones': []}

    def parts(self, **door):
        from lib.studio.render3d.shapes import room_scenes
        spec = build_sketch_spec(self.door_room(**door), [VFE], {})
        meshes = room_scenes(spec)[0].meshes
        return {m.name.removeprefix('door-'): m for m in meshes if m.group == 'door'}

    @staticmethod
    def centre(mesh):
        xs, ys, _ = zip(*mesh.verts)
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def test_far_wall_door_spec_knows_the_room_side(self):
        spec = build_sketch_spec(self.door_room(opens='pocket', leaf_state='ajar'), [VFE], {})
        door = spec['objects'][0]
        self.assertEqual((door['inward'], door['opens'], door['leaf_state'], door['hinge_sign']),
                         ([0, -1], 'pocket', 'ajar', 1))

    def test_side_wall_door_with_its_footprint_across_still_runs_along_the_wall(self):
        # A model slip: a left-wall door given 0.9 m of width_x instead of depth_y keeps its y1 hinge.
        spec = build_sketch_spec(self.door_room(x=0.0, y=0.5, width_x=0.9 / W, depth_y=0, hinge_side='y1'), [VFE], {})
        self.assertEqual((spec['objects'][0]['inward'], spec['objects'][0]['hinge_sign']), ([1, 0], 1))

    def test_open_up_and_over_panel_lies_under_the_lintel_inside(self):
        panel = self.parts(opens='up-and-over', leaf_state='open')['panel']
        _, y = self.centre(panel)
        self.assertLess(y, D - 0.5)                          # projects into the room, not out of it
        self.assertGreater(min(v[2] for v in panel.verts), 1.8)

    def test_closed_hinged_door_covers_its_opening(self):
        parts = self.parts(opens='inward', leaf_state='closed')
        self.assertIn('leaf-panel', parts)
        self.assertNotIn('void', parts)

    def test_open_inward_leaf_stands_in_the_room_at_the_hinge(self):
        x, y = self.centre(self.parts(opens='inward', leaf_state='open')['leaf-panel'])
        self.assertLess(y, D - 0.3)                          # turned into the room, ~half a leaf off the far wall
        self.assertGreater(x, 1.5 + 0.3)                     # on the x1 (hinge) side of the door centre

    def test_open_outward_leaf_is_beyond_the_wall(self):
        _, y = self.centre(self.parts(opens='outward', leaf_state='open')['leaf-panel'])
        self.assertGreater(y, D + 0.3)

    def test_folded_leaf_lies_flat_on_the_wall_beside_the_opening(self):
        x, y = self.centre(self.parts(opens='inward', leaf_state='folded')['leaf-panel'])
        self.assertGreater(y, D - 0.15)
        self.assertGreater(x, 1.5 + 0.7)                     # past the hinge jamb, flat on the wall

    def test_doorway_without_leaf_is_an_opening(self):
        parts = self.parts(opens='none')
        self.assertIn('void', parts)
        self.assertFalse([p for p in parts if 'leaf' in p])

    def test_open_pocket_door_hides_its_leaf_and_sliding_door_moves_aside(self):
        self.assertFalse([p for p in self.parts(opens='pocket', leaf_state='open') if 'leaf' in p])
        x, _ = self.centre(self.parts(opens='sliding', leaf_state='open')['leaf-panel'])
        self.assertAlmostEqual(x, 1.5 + 0.8, delta=0.1)      # one leaf width toward hinge_side x1

    def test_side_wall_door_opens_into_the_room(self):
        parts = self.parts(x=0.0, y=0.5, width_x=0, depth_y=0.9 / D, hinge_side='y1', opens='inward',
                           leaf_state='open')
        x, y = self.centre(parts['leaf-panel'])
        self.assertGreater(x, 0.3)                           # off the left wall, inside
        self.assertGreater(y, D / 2 + 0.3)                   # at the y1 hinge end

    def test_furniture_in_an_inward_swing_is_reported(self):
        plan = grocery()
        plan['objects'].append(obj('stool', 'Stool', 1.1, 1.3, 0.3, 0.55, h=0.6))  # inside the door's swing
        plan['objects'][0]['opens'] = ''
        self.assertEqual(issues(plan), [])                   # mechanism unstated: not checked
        plan['objects'][0]['opens'] = 'inward'
        self.assertEqual(issues(plan), ['stool stands in the swing of shop-entrance-doorway '
                                        '(0.90 m leaf opening inward)'])
        plan['objects'][0]['opens'] = 'outward'
        self.assertEqual(issues(plan), [])


if __name__ == '__main__':
    unittest.main()
