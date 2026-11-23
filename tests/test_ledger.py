"""Story ledger: unexplained moves, seat swaps and wardrobe changes, and their enforcement in the screenwriter."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import ledger
from lib.studio.screenwriter import enforce, episodes, passes, scenes

CAR = 'Black-SUV-Interior-To-Entrance'


def actor(name, position='', seat=None, look=None, motion=''):
    return {'name': name, 'position': position, 'vehicle_position': seat, 'visual_ref': look,
            'motion_action': motion, 'in_frame': True}


def panel(idx, *actors, location=CAR, motion=''):
    return {'panel_index': idx, 'location_references': [location] if location else [],
            'motion_action': motion, 'state': {'actors': list(actors)}}


def scene(sid, *panels, **extra):
    return {'scene_id': sid, 'location': CAR, 'panels': list(panels), **extra}


class PanelTests(unittest.TestCase):
    def test_seat_change_needs_a_move(self):
        s = scene(1, panel(1, actor('Girl', seat='rear-right')), panel(2, actor('Girl', seat='rear-center')))
        self.assertEqual(len(ledger.check([s])), 1)
        s['panels'][1]['state']['actors'][0]['motion_action'] = 'slides to the middle seat'
        self.assertEqual(ledger.check([s]), [])

    def test_frame_words_do_not_excuse_a_move(self):
        s = scene(1, panel(1, actor('Girl', seat='rear-right')),
                  panel(2, actor('Girl', seat='rear-center', motion='glances toward frame-left'), motion='range of emotions'))
        self.assertEqual(len(ledger.check([s])), 1)

    def test_room_anchor_change_and_cargo_count_as_places(self):
        s = scene(1, panel(1, actor('Jack', 'at [sofa-left]'), location='Flat-View-From-Entrance'),
                  panel(2, actor('Jack', 'at [kitchen-door]'), location='Flat-View-To-Entrance'))
        self.assertIn('[sofa-left] → [kitchen-door]', str(ledger.check([s])[0]))
        s = scene(1, panel(1, actor('Girl', seat='cargo')), panel(2, actor('Girl', seat='rear-center')))
        self.assertEqual(len(ledger.check([s])), 1)

    def test_wardrobe_only_when_both_refs_named(self):
        s = scene(1, panel(1, actor('Girl', seat='rear-right', look='Girl-Casual')),
                  panel(2, actor('Girl', seat='rear-right', look='Girl-Gown')))
        self.assertIn('wardrobe', str(ledger.check([s])[0]))
        s['panels'][1]['state']['actors'][0]['visual_ref'] = None
        self.assertEqual(ledger.check([s]), [])


class BoundaryTests(unittest.TestCase):
    """Mafia S4 → S5 and S1 → S2."""

    def test_seat_swap_across_a_continuous_cut(self):
        s4 = scene(4, panel(9, actor('Girl', 'in the middle of the back seat')))
        s5 = scene(5, panel(1, actor('Girl', 'in the rear passenger-side seat of the stopped SUV'), location='Forest-View-Primary'))
        self.assertIn('rear-center, this one starts in rear-right', str(ledger.check([s4, s5])[0]))
        self.assertEqual(ledger.check([s4, {**s5, 'transition_in': 'time_skip'}]), [])

    def test_getting_out_between_scenes_is_allowed(self):
        s4 = scene(4, panel(9, actor('Kidnapper', seat='rear-left')))
        s5 = scene(5, panel(1, actor('Kidnapper', 'outside the rear passenger door', seat='outside'), location='Forest-View-Primary'))
        self.assertEqual(ledger.check([s4, s5]), [])

    def test_seated_without_entering(self):
        s1 = scene(1, panel(9, actor('Girl', 'leaning out of the open rear door of the Black-SUV-Exterior'),
                            location='Street-View-Primary'))
        s2 = scene(2, panel(1, actor('Girl', seat='rear-right'), actor('Kidnapper', seat='rear-left')))
        issues = ledger.check([s1, s2], {'Black-SUV'})
        self.assertEqual([i.character for i in issues], ['Kidnapper'])
        outdoor = scene(2, panel(1, actor('Kidnapper', 'in the rear left seat of the Black-SUV', seat='rear-left'),
                                 location='Forest-View-Primary'))
        self.assertEqual([i.character for i in ledger.check([s1, outdoor], {'Black-SUV'})], ['Kidnapper'])
        empty_street = scene(1, panel(9, actor('Girl', 'on the sidewalk'), location='Street-View-Primary'))
        self.assertEqual(ledger.check([empty_street, s2], {'Black-SUV'}), [])


class DeclaredTests(unittest.TestCase):
    def test_generated_panels_against_entry_and_exit_state(self):
        spec = {'scene_local_id': 3, 'location': CAR,
                'entry_state': [{'character': 'Girl', 'vehicle_position': 'rear-right', 'visual_ref': 'Girl-Casual'}],
                'exit_state': [{'character': 'Girl', 'vehicle_position': 'rear-center', 'visual_ref': 'Girl-Casual'}]}
        ok = [panel(1, actor('Girl', seat='rear-right', look='Girl-Casual')),
              panel(2, actor('Girl', seat='rear-center', look='Girl-Casual'))]
        self.assertEqual(ledger.declared_issues(ok, spec), [])
        bad = [panel(1, actor('Girl', seat='rear-left', look='Girl-Gown')), panel(2, actor('Girl', seat='rear-right'))]
        self.assertEqual(len(ledger.declared_issues(bad, spec)), 3)

    def test_screenplay_exit_to_entry(self):
        def sc(i, entry, exit_, transition='continuous'):
            return {'scene_local_id': i, 'transition_in': transition, 'entry_state': entry, 'exit_state': exit_}
        girl_mid = {'character': 'Girl', 'place': 'back seat', 'vehicle_position': 'rear-center'}
        girl_right = {'character': 'Girl', 'place': 'back seat', 'vehicle_position': 'rear-right'}
        kid = {'character': 'Kidnapper', 'place': 'back seat', 'vehicle_position': 'rear-left'}
        play = {'episodes': [{'episode_id': 1, 'scenes': [sc(1, [girl_right], [girl_mid])]},
                             {'episode_id': 2, 'scenes': [sc(1, [girl_right, kid], [girl_right])]}]}
        self.assertEqual(sorted(i.character for i in ledger.screenplay_issues(play)), ['Girl', 'Kidnapper'])
        play['episodes'][1]['scenes'][0]['transition_in'] = 'time_skip'
        self.assertEqual(ledger.screenplay_issues(play), [])
        jack = {'character': 'Jack', 'place': 'sofa-left', 'vehicle_position': 'none'}
        moved = {**jack, 'place': 'kitchen-door'}
        play = {'episodes': [{'episode_id': 1, 'scenes': [sc(1, [jack], [jack]), sc(2, [moved], [moved])]}]}
        self.assertIn('sofa-left → kitchen-door', str(ledger.screenplay_issues(play)[0]))


class ScreenwriterWiringTests(unittest.TestCase):
    SPEC = {'scene_local_id': 2, 'location': CAR}
    PREV = {'panel': panel(9, actor('Girl', seat='rear-center')), 'scene': scene(1)}

    def p1a(self, seat):
        return {'panels': [{'panel_index': 1, 'motion_action': '', 'state': {'actors': [actor('Girl', seat=seat)]}}]}

    def test_retry_is_kept_only_when_it_reduces_issues(self):
        fixed = self.p1a('rear-center')
        rerun = mock.Mock(return_value=fixed)
        self.assertIs(enforce._enforce_ledger(self.p1a('rear-right'), rerun, self.SPEC, self.PREV, set()), fixed)
        self.assertIn('rear-center', rerun.call_args[0][0])
        first = self.p1a('rear-right')
        self.assertIs(enforce._enforce_ledger(first, mock.Mock(return_value=self.p1a('rear-left')), self.SPEC, self.PREV, set()), first)

    def test_clean_answer_makes_no_retry(self):
        rerun = mock.Mock()
        enforce._enforce_ledger(self.p1a('rear-center'), rerun, self.SPEC, self.PREV, set())
        rerun.assert_not_called()

    def test_every_scene_gets_the_previous_scene_exit(self):
        seen = []

        def fake(**kw):
            seen.append(kw['prev_episode_exit'])
            sid = kw['scene_spec']['scene_local_id']
            return {'scene_id': sid, 'panels': [panel(1, actor('Girl', seat=f'rear-{"right" if sid == 1 else "left"}'))]}

        episode = ('{"scenes": [{"scene_local_id": 1, "panel_count": 9}, {"scene_local_id": 2, "panel_count": 9},'
                   ' {"scene_local_id": 3, "panel_count": 9, "transition_in": "new_location"}]}')
        with mock.patch.object(scenes, 'generate_scene_4pass', side_effect=fake):
            scenes.analyze_scenes_for_episode(1, episode, {}, {'format': {}}, None, [], prev_episode_exit={'visual_end': 'x'})
        self.assertEqual(seen[0], {'visual_end': 'x'})
        self.assertEqual(seen[1]['state']['actors'][0]['vehicle_position'], 'rear-right')
        self.assertIsNone(seen[2])

    def test_pass2_block_for_car_scenes_and_none_without_anchors(self):
        p1 = {'panels': [{'panel_index': 1, 'scale': 'MS'}]}
        p1a = {'panels': [{'panel_index': 1, 'state': {'actors': [actor('Girl', seat='rear-right'), actor('Kid', seat='rear-left')]}}]}
        refs = {'Black-SUV-Exterior': {'visual_desc': 'black SUV'}}
        block = passes._pass2_blocking_block({'location': CAR}, p1, p1a, None, refs, {})
        self.assertIn('P1: vehicle_shot=front-center-back', block)
        self.assertIn('Kid — rear left seat (behind the driver): frame-right', block)
        self.assertEqual(passes._pass2_blocking_block({'location': 'Flat-View-From-Entrance'}, p1, p1a, None, refs, {}), '')

    def test_screenplay_retry_on_declared_contradiction(self):
        def play(seat):
            entry = [{'character': 'Girl', 'place': 'x', 'vehicle_position': seat, 'visual_ref': 'G'}]
            exit_ = [{'character': 'Girl', 'place': 'x', 'vehicle_position': 'rear-center', 'visual_ref': 'G'}]
            return {'episodes': [{'episode_id': 1, 'scenes': [
                {'scene_local_id': 1, 'panel_count': 9, 'transition_in': 'continuous', 'entry_state': exit_, 'exit_state': exit_},
                {'scene_local_id': 2, 'panel_count': 9, 'transition_in': 'continuous', 'entry_state': entry, 'exit_state': exit_}]}]}
        llm = mock.Mock()
        llm.make_json.side_effect = [play('rear-right'), play('rear-center')]
        out = episodes.analyze_episodes_master('story', {}, {'format': {'panel_count_options': [9]}}, llm)
        self.assertEqual(out['episodes'][0]['scenes'][1]['entry_state'][0]['vehicle_position'], 'rear-center')
        self.assertIn('CONTINUITY ERRORS', llm.make_json.call_args_list[1][0][0])


if __name__ == '__main__':
    unittest.main()
