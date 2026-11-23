"""Truth-aware room generation: banding, persistence, edits, and gating."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project
from lib.studio import critic, room_qa


def _png_bytes(color=(10, 20, 30), size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


class BandingTests(unittest.TestCase):
    def test_action_bands(self):
        self.assertEqual(critic.decide_room_view_action(4), 'regenerate')
        self.assertEqual(critic.decide_room_view_action(5), 'regenerate_with_instructions')
        self.assertEqual(critic.decide_room_view_action(7), 'regenerate_with_instructions')
        self.assertEqual(critic.decide_room_view_action(8), 'targeted_edit')
        self.assertEqual(critic.decide_room_view_action(9), 'accept')
        self.assertEqual(critic.decide_room_view_action(10), 'accept')

    def test_threshold_must_be_nine_for_edit_band(self):
        # A pass threshold of 7 would accept before the edit band is reachable.
        self.assertEqual(
            critic.decide_room_view_action(7, pass_threshold=7), 'accept'
        )


class NormalizeTests(unittest.TestCase):
    def test_old_schema_is_normalized(self):
        result = critic.normalize_room_view_qa({
            'consistency_score': 10,
            'geometry_score': 10,
            'needs_regeneration': False,
            'issues': [],
            'regeneration_prompt': '',
        }, pass_threshold=9)
        self.assertEqual(result['style_score'], 10)
        self.assertEqual(result['architecture_score'], 10)
        self.assertEqual(result['geometry_score'], 10)
        self.assertEqual(result['overall_score'], 10)
        self.assertEqual(result['action'], 'accept')
        self.assertFalse(result['needs_regeneration'])

    def test_overall_is_minimum(self):
        result = critic.normalize_room_view_qa({
            'style_score': 9,
            'architecture_score': 6,
            'geometry_score': 8,
        }, pass_threshold=9)
        self.assertEqual(result['overall_score'], 6)
        self.assertEqual(result['action'], 'regenerate_with_instructions')
        self.assertEqual(result['consistency_score'], 6)

    def test_structured_issues_keep_text_compatibility(self):
        result = critic.normalize_room_view_qa({
            'style_score': 5,
            'architecture_score': 5,
            'geometry_score': 5,
            'issues': [{
                'category': 'style', 'severity': 'high', 'object': 'floor',
                'expected': 'dark concrete', 'observed': 'light parquet',
            }],
        }, pass_threshold=9)
        self.assertIn('[style]', result['issues'][0])
        self.assertIn('dark concrete', result['issues'][0])
        self.assertEqual(result['issue_details'][0]['object'], 'floor')

    def test_api_error_blocks_without_regeneration(self):
        result = critic.normalize_room_view_qa(
            {'api_error': True, 'issues': ['boom']}, pass_threshold=9
        )
        self.assertEqual(result['action'], 'blocked')
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['needs_regeneration'])


_EDIT = {'op': 'remove', 'target': 'clipboard', 'from': 'entrance wall', 'to': '', 'details': ''}


class LocalFixRoutingTests(unittest.TestCase):
    def _norm(self, score, edits, issues=()):
        return critic.normalize_room_view_qa({
            'style_score': score, 'architecture_score': score, 'geometry_score': score,
            'issues': list(issues), 'edit_instructions': edits,
        }, pass_threshold=9)

    def test_local_defect_in_instruction_band_is_edited(self):
        issue = {'category': 'architecture', 'severity': 'high', 'object': 'clipboard',
                 'expected': 'one', 'observed': 'two'}
        self.assertEqual(self._norm(7, [_EDIT], [issue])['action'], 'targeted_edit')
        self.assertEqual(self._norm(5, [_EDIT])['action'], 'targeted_edit')

    def test_global_or_wide_defects_still_regenerate(self):
        style = {'category': 'style', 'severity': 'high', 'object': 'floor',
                 'expected': 'concrete', 'observed': 'parquet'}
        self.assertEqual(self._norm(7, [_EDIT], [style])['action'],
                         'regenerate_with_instructions')
        too_many = [_EDIT] * (critic.ROOM_QA_MAX_LOCAL_EDITS + 1)
        self.assertEqual(self._norm(7, too_many)['action'], 'regenerate_with_instructions')
        self.assertEqual(self._norm(7, [])['action'], 'regenerate_with_instructions')
        self.assertEqual(self._norm(4, [_EDIT])['action'], 'regenerate')


class SeverityTests(unittest.TestCase):
    def _norm(self, score, severities, **extra):
        issues = [{'category': 'architecture', 'severity': sev, 'object': 'x',
                   'expected': 'a', 'observed': 'b'} for sev in severities]
        return critic.normalize_room_view_qa({
            'style_score': score, 'architecture_score': score, 'geometry_score': score,
            'issues': issues, **extra,
        }, pass_threshold=9)

    def test_only_low_issues_at_seven_pass(self):
        result = self._norm(7, ['low', 'low'])
        self.assertEqual((result['action'], result['status']), ('accept', 'passed'))
        self.assertFalse(result['needs_regeneration'])

    def test_medium_issue_or_low_score_still_fails(self):
        self.assertNotEqual(self._norm(7, ['low', 'medium'])['action'], 'accept')
        self.assertNotEqual(self._norm(6, ['low'])['action'], 'accept')

    def test_api_error_is_never_accepted(self):
        self.assertEqual(self._norm(7, ['low'], api_error=True)['action'], 'blocked')


class RenderDescTests(unittest.TestCase):
    def test_corrections_are_composed_without_mutating_visual_desc(self):
        data = {'visual_desc': 'Steel room.', 'qa_corrections': ['Fix the floor.']}
        composed = room_qa.compose_render_desc(data)
        self.assertIn('Steel room.', composed)
        self.assertIn('PERSISTED QA CORRECTIONS', composed)
        self.assertIn('Fix the floor.', composed)
        self.assertEqual(data['visual_desc'], 'Steel room.')


class _ProjectMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir
        self.base = 'Test-Room'
        self.vfe = f'{self.base}-View-From-Entrance'
        self.vte = f'{self.base}-View-To-Entrance'
        self.vte_json = self.ref_dir / 'test-room-view-to-entrance.json'
        self.vte_png = self.ref_dir / 'test-room-view-to-entrance.png'

    def write_view(self, name, color, size=(32, 32), **extra):
        data = {'name': name, 'type': 'Room', 'visual_desc': 'Steel room.',
                'style_reference': '', **extra}
        safe = name.lower()
        (self.ref_dir / f'{safe}.json').write_text(json.dumps(data))
        (self.ref_dir / f'{safe}.png').write_bytes(_png_bytes(color, size))
        return data


class FakeQA:
    """Vision judge with a scripted sequence of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.edits = []

    def analyze_image(self, image, prompt, schema=None):
        self.prompts.append(prompt)
        response = self.responses.pop(0) if self.responses else self.responses_last
        self.responses_last = response
        if isinstance(response, Exception):
            raise response
        return response

    def edit_image(self, src_img, prompt, refs=None, **kwargs):
        self.edits.append(prompt)
        return _png_bytes((200, 10, 10))


def _qa(score, action=None, **extra):
    return {
        'style_score': score,
        'architecture_score': score,
        'geometry_score': score,
        'issues': [],
        'regeneration_prompt': '',
        'edit_instructions': [],
        'edit_prompt': '',
        **extra,
    }


class QaLoopTests(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write_view(self.vfe, (10, 10, 10))
        self.write_view(self.vte, (20, 20, 20))

    def test_targeted_edit_commits_only_better_candidate(self):
        llm = FakeQA([_qa(8, edit_prompt='Remove the extra chair.'), _qa(10)])
        summary = room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9, max_attempts=2
        )
        self.assertEqual(summary['status'], 'passed')
        self.assertEqual(len(llm.edits), 1)
        # The accepted candidate replaced the live PNG.
        with Image.open(self.vte_png) as img:
            self.assertEqual(img.getpixel((0, 0)), (200, 10, 10))
        data = json.loads(self.vte_json.read_text())
        self.assertEqual(data['qa']['status'], 'passed')
        self.assertEqual(data['qa']['scores']['overall'], 10)

    def test_passed_view_is_not_rejudged_until_its_image_changes(self):
        room_qa.run_view_qa_loop(self.project, FakeQA([_qa(10)]), self.vte, config={}, threshold=9)
        idle = FakeQA([])
        summary = room_qa.run_view_qa_loop(self.project, idle, self.vte, config={}, threshold=9)
        self.assertEqual((summary['status'], idle.prompts), ('passed', []))
        self.vte_png.write_bytes(_png_bytes((1, 2, 3)))
        changed = FakeQA([_qa(10)])
        room_qa.run_view_qa_loop(self.project, changed, self.vte, config={}, threshold=9)
        self.assertEqual(len(changed.prompts), 1)

    def test_api_error_never_overwrites_live_png(self):
        before = self.vte_png.read_bytes()
        llm = FakeQA([RuntimeError('network down')])
        summary = room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9, max_attempts=2
        )
        self.assertEqual(summary['status'], 'blocked')
        self.assertEqual(self.vte_png.read_bytes(), before)
        data = json.loads(self.vte_json.read_text())
        self.assertEqual(data['qa']['status'], 'blocked')

    def test_corrections_are_replaced_not_accumulated(self):
        class SameScoreLLM(FakeQA):
            def make_image(self, prompt, refs=None, **kwargs):
                return _png_bytes((99, 99, 99))

        data = json.loads(self.vte_json.read_text())
        data['qa_corrections'] = ['Stale fix A.', 'Stale fix B.']
        self.vte_json.write_text(json.dumps(data))
        llm = SameScoreLLM([
            _qa(6, regeneration_prompt='Fix one.'), _qa(6),
            _qa(6, regeneration_prompt='Fix two.'), _qa(6),
        ])
        room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9,
            max_attempts=3, edit_attempts=0,
        )
        self.assertEqual(json.loads(self.vte_json.read_text())['qa_corrections'], ['Fix two.'])

    def test_failed_edits_escalate_to_rerender(self):
        class NoGainLLM(FakeQA):
            def __init__(self, responses):
                super().__init__(responses)
                self.renders = []

            def make_image(self, prompt, refs=None, **kwargs):
                self.renders.append(prompt)
                return _png_bytes((99, 99, 99))

        local = _qa(7, edit_instructions=[_EDIT], edit_prompt='Remove the clipboard.')
        # attempt 1: local fix → edit scores no better; attempt 2: same verdict
        # must re-render instead of editing again.
        llm = NoGainLLM([local, _qa(7), local, _qa(7)])
        room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9,
            max_attempts=3, edit_attempts=1,
        )
        self.assertEqual(len(llm.edits), 1)
        self.assertEqual(len(llm.renders), 1)
        self.assertIn('Remove the clipboard.', llm.renders[0])

    def test_failed_instructed_render_keeps_live_png(self):
        class SameScoreLLM(FakeQA):
            def make_image(self, prompt, refs=None, **kwargs):
                return _png_bytes((99, 99, 99))

        before = self.vte_png.read_bytes()
        llm = SameScoreLLM([_qa(6, regeneration_prompt='Fix the floor.')] * 3)
        summary = room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9,
            max_attempts=2, edit_attempts=0,
        )
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(self.vte_png.read_bytes(), before)
        data = json.loads(self.vte_json.read_text())
        self.assertEqual(data['qa']['status'], 'failed')
        self.assertTrue(data['qa_corrections'])

    def test_accept_persists_without_rendering(self):
        llm = FakeQA([_qa(9)])
        summary = room_qa.run_view_qa_loop(
            self.project, llm, self.vte, config={}, threshold=9, max_attempts=2
        )
        self.assertEqual(summary['status'], 'passed')
        self.assertEqual(llm.edits, [])
        self.assertEqual(len(llm.prompts), 1)


class InvalidationTests(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for suffix in room_qa.DERIVED_SUFFIXES:
            name = f'{self.base}-{suffix}'
            self.write_view(name, (30, 30, 30), qa={'status': 'passed'},
                            qa_corrections=['old correction'])

    def test_vfe_change_invalidates_vte_and_derived(self):
        self.write_view(self.vte, (20, 20, 20), qa={'status': 'passed'})
        changed = room_qa.invalidate_dependents(
            self.project, self.base, 'View-From-Entrance'
        )
        self.assertIn(self.vte, changed)
        for suffix in room_qa.DERIVED_SUFFIXES:
            self.assertIn(f'{self.base}-{suffix}', changed)
        vte = json.loads(self.vte_json.read_text())
        self.assertTrue(vte['needs_regenerate'])
        self.assertEqual(vte['qa']['status'], 'pending')
        self.assertEqual(vte['qa_corrections'], [])

    def test_vte_change_invalidates_only_derived(self):
        self.write_view(self.vte, (20, 20, 20), qa={'status': 'passed'})
        changed = room_qa.invalidate_dependents(self.project, self.base, 'View-To-Entrance')
        self.assertNotIn(self.vte, changed)
        self.assertEqual(len(changed), len(room_qa.DERIVED_SUFFIXES))


class OrchestrationTests(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        anchors = {'room_m': [4.0, 6.0], 'objects': [], 'zones': []}
        # 4:3 is the expected framing for a 4 m wall in a 3 m-high room.
        self.write_view(self.vfe, (10, 10, 10), size=(40, 30), anchor_points=anchors)
        self.write_view(self.vte, (20, 20, 20), size=(40, 30))

    class ImageLLM(FakeQA):
        def make_image(self, prompt, refs=None, **kwargs):
            sizes = {
                '4:3': (40, 30), '3:4': (30, 40),
                '16:9': (48, 27), '9:16': (27, 48),
                '1:1': (32, 32),
            }
            size = sizes.get(kwargs.get('aspect_ratio'), (32, 32))
            return _png_bytes((120, 120, 120), size)

    def test_verified_vte_unlocks_derived_views(self):
        llm = self.ImageLLM([_qa(10)] * 12)
        summary = room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        self.assertIn(self.base, summary['passed_vte'])
        self.assertNotIn(self.base, summary['failed_vte'])
        self.assertNotIn('error', summary['rooms'][self.base])
        for suffix in room_qa.DERIVED_SUFFIXES:
            png = self.ref_dir / f'{self.base.lower()}-{suffix.lower()}.png'
            self.assertTrue(png.exists(), f'{suffix} was not rendered')

    def test_unverified_vte_blocks_derived_views(self):
        # VFE passes; max_attempts=1: a failing VTE score never gets a render/retry.
        llm = self.ImageLLM([_qa(10), _qa(4)])
        summary = room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        self.assertIn(self.base, summary['failed_vte'])
        self.assertNotIn(self.base, summary['passed_vte'])
        for suffix in room_qa.DERIVED_SUFFIXES:
            png = self.ref_dir / f'{self.base.lower()}-{suffix.lower()}.png'
            self.assertFalse(png.exists(), f'{suffix} rendered before VTE passed')

    def test_vfe_is_checked_against_description_and_named_positions(self):
        data = json.loads((self.ref_dir / 'test-room-view-from-entrance.json').read_text())
        data['room_vocabulary'] = [{'id': 'server-rack-row', 'description': 'left wall racks'}]
        (self.ref_dir / 'test-room-view-from-entrance.json').write_text(json.dumps(data))
        llm = self.ImageLLM([_qa(10)] * 12)
        room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        vfe_prompt = llm.prompts[0]
        self.assertIn('BASE-TRUTH', vfe_prompt)
        self.assertIn('Steel room.', vfe_prompt)
        self.assertIn('[server-rack-row] left wall racks', vfe_prompt)
        self.assertIn('unrequested door', vfe_prompt)
        self.assertIn('BEHIND THE CAMERA, NOT VISIBLE: the entrance wall', vfe_prompt)
        self.assertIn('never require such lettering', vfe_prompt)

    def test_room_left_without_anchors_is_an_error(self):
        self.write_view(self.vfe, (10, 10, 10), size=(40, 30))
        summary = room_qa.run_room_views(
            self.project, self.ImageLLM([_qa(10)] * 12), {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        self.assertEqual(summary['rooms'][self.base]['error'], 'anchors missing')

    def test_failed_vfe_blocks_vte_and_derived_views(self):
        vte_before = self.vte_png.read_bytes()
        llm = self.ImageLLM([_qa(4)])
        summary = room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        self.assertEqual(summary['failed_vfe'], [self.base])
        self.assertNotIn('View-To-Entrance', summary['rooms'][self.base]['views'])
        self.assertEqual(len(llm.prompts), 1)  # only the VFE was judged
        self.assertEqual(self.vte_png.read_bytes(), vte_before)
        for suffix in room_qa.DERIVED_SUFFIXES:
            png = self.ref_dir / f'{self.base.lower()}-{suffix.lower()}.png'
            self.assertFalse(png.exists(), f'{suffix} rendered from an unverified VFE')

    def test_passed_vfe_is_locked(self):
        llm = self.ImageLLM([_qa(10)] * 12)
        room_qa.run_room_views(self.project, llm, {}, rooms=[self.base],
                               use_sketches=False, pass_threshold=9, max_attempts=1)
        llm = self.ImageLLM([_qa(10)] * 12)
        room_qa.run_room_views(self.project, llm, {}, rooms=[self.base],
                               use_sketches=False, pass_threshold=9, max_attempts=1)
        self.assertFalse(any('BASE-TRUTH' in prompt for prompt in llm.prompts))

    def test_corrected_vfe_invalidates_anchors_and_vte(self):
        llm = self.ImageLLM([_qa(8, edit_prompt='Remove the unrequested left door.'), _qa(10)])
        summary = room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        self.assertEqual(summary['rooms'][self.base]['views']['View-From-Entrance']['status'],
                         'passed')
        self.assertEqual(len(llm.edits), 1)
        vfe = json.loads((self.ref_dir / 'test-room-view-from-entrance.json').read_text())
        self.assertNotIn('anchor_points', vfe)  # FakeQA cannot re-derive anchors
        # VTE was re-rendered from the corrected VFE (grey 120, not the old 20).
        with Image.open(self.vte_png) as img:
            self.assertEqual(img.getpixel((0, 0)), (120, 120, 120))

    def test_failed_derived_render_is_reported_not_missing(self):
        class NoImageLLM(self.ImageLLM):
            def make_image(self, prompt, refs=None, **kwargs):
                return None  # the backend logged an API error and returned nothing

        summary = room_qa.run_room_views(
            self.project, NoImageLLM([_qa(10)] * 4), {}, rooms=[self.base],
            use_sketches=False, pass_threshold=9, max_attempts=1,
        )
        views = summary['rooms'][self.base]['views']
        for suffix in room_qa.DERIVED_SUFFIXES:
            self.assertEqual(views[suffix]['status'], 'render_failed', suffix)
            data = json.loads((self.ref_dir / f'{self.base.lower()}-{suffix.lower()}.json')
                              .read_text())
            self.assertEqual(data['qa']['status'], 'pending')  # never judged

    def test_rerendered_vfe_drops_anchors_and_its_passed_lock(self):
        path = self.ref_dir / 'test-room-view-from-entrance.json'
        data = json.loads(path.read_text())
        data.update(needs_regenerate=True, qa={'status': 'passed'})
        path.write_text(json.dumps(data))
        llm = self.ImageLLM([_qa(10)] * 12)
        room_qa.run_room_views(self.project, llm, {}, rooms=[self.base],
                               use_sketches=False, pass_threshold=9, max_attempts=1)
        self.assertNotIn('anchor_points', json.loads(path.read_text()))
        self.assertTrue(any('BASE-TRUTH' in prompt for prompt in llm.prompts))

    def test_summary_is_written(self):
        llm = self.ImageLLM([_qa(10)] * 12)
        room_qa.run_room_views(
            self.project, llm, {}, rooms=[self.base], use_sketches=False,
            pass_threshold=9, max_attempts=1,
        )
        summary = json.loads((self.ref_dir / room_qa.QA_SUMMARY_NAME).read_text())
        self.assertEqual(summary['passed_vte'], [self.base])
        self.assertEqual(summary['rooms'][self.base]['views']['View-To-Entrance']['status'],
                         'passed')



class OutdoorChainTests(unittest.TestCase):
    """View-Primary is judged against its description; the three station views are built from it."""
    base = 'Cafe-Street'
    station_views = ('View-Opposite', 'View-Ortho-Primary', 'View-Ortho-Opposite')

    class ImageLLM(FakeQA):
        renders: list

        def make_image(self, prompt, refs=None, **kwargs):
            self.renders.append((prompt, kwargs.get('aspect_ratio')))
            return _png_bytes((120, 120, 120), {'16:9': (48, 27)}.get(kwargs.get('aspect_ratio'), (27, 48)))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref_dir = Path(self.tmp.name)
        self.project = Project()
        self.project.ref_dir = self.ref_dir
        anchors = {'room_m': [20, 60], 'station': [0.7, 0.5], 'objects': [], 'zones': []}
        for suffix, extra in (('View-Primary', {'anchor_points': anchors}),
                              ('View-Opposite', {'style_reference': f'{self.base}-View-Primary'})):
            name = f'{self.base}-{suffix}'
            (self.ref_dir / f'{name.lower()}.json').write_text(json.dumps(
                {'name': name, 'type': 'Outdoor', 'visual_desc': 'Brick cafe on the RIGHT.', **extra}))
        (self.ref_dir / 'cafe-street-view-primary.png').write_bytes(_png_bytes((10, 10, 10), (48, 27)))

    def run_chain(self, responses):
        llm = self.ImageLLM(responses)
        llm.renders = []
        summary = room_qa.run_room_views(self.project, llm, {}, rooms=[self.base], use_sketches=False,
                                         pass_threshold=9, max_attempts=1)
        return summary, llm

    def png(self, suffix):
        return self.ref_dir / f'{self.base.lower()}-{suffix.lower()}.png'

    def test_verified_primary_unlocks_the_station_views_on_a_landscape_plate(self):
        summary, llm = self.run_chain([_qa(10)] * 4)
        self.assertEqual(summary['outdoor']['failed'], [])
        views = summary['outdoor']['locations'][self.base]['views']
        self.assertEqual({s: views[s]['status'] for s in self.station_views}, dict.fromkeys(self.station_views, 'passed'))
        for suffix in self.station_views:
            with Image.open(self.png(suffix)) as img:
                self.assertEqual(img.size, (48, 27), suffix)
        prompt, aspect = llm.renders[0]
        self.assertEqual(aspect, '16:9')
        self.assertIn('CINEMATIC LOCATION REFERENCE', prompt)
        self.assertNotIn('Close-up', prompt)
        ortho_judge = next(p for p in llm.prompts if 'Image 2 is "View-Ortho-Primary"' in p)
        self.assertIn('OUTDOOR LOCATION VIEW', ortho_judge)
        self.assertIn('turned 90° RIGHT', ortho_judge)
        self.assertIn('BEHIND THE CAMERA, NOT VISIBLE: everything the description places on the LEFT', ortho_judge)

    def test_primary_is_judged_against_its_description(self):
        _, llm = self.run_chain([_qa(10)] * 4)
        self.assertIn('BASE-TRUTH reference "View-Primary"', llm.prompts[0])
        self.assertIn('Brick cafe on the RIGHT.', llm.prompts[0])
        self.assertIn('image-right edge', llm.prompts[0])

    def test_failed_primary_blocks_the_station_views(self):
        summary, llm = self.run_chain([_qa(4)])
        self.assertEqual(summary['outdoor']['failed'], [self.base])
        written = json.loads((self.ref_dir / room_qa.QA_SUMMARY_NAME).read_text())
        self.assertEqual(written['outdoor']['failed'], [self.base])
        self.assertEqual(len(llm.prompts), 1)
        for suffix in self.station_views:
            self.assertFalse(self.png(suffix).exists(), f'{suffix} rendered from an unverified View-Primary')

    def test_location_left_without_anchors_fails(self):
        path = self.ref_dir / 'cafe-street-view-primary.json'
        data = json.loads(path.read_text())
        del data['anchor_points']
        path.write_text(json.dumps(data))
        summary, _ = self.run_chain([_qa(10)] * 8)
        self.assertEqual(summary['outdoor']['failed'], [self.base])
        self.assertEqual(summary['outdoor']['locations'][self.base]['error'], 'anchors missing')

    def test_changed_primary_invalidates_its_station_views(self):
        self.run_chain([_qa(10)] * 4)
        changed = room_qa.invalidate_dependents(self.project, self.base, 'View-Primary')
        self.assertEqual(sorted(changed), sorted(f'{self.base}-{s}' for s in self.station_views))

    def test_anchors_ignore_a_stale_opposite_image(self):
        from lib.studio.artist.room_anchors import _current_image
        name = f'{self.base}-View-Opposite'
        self.project.character_images[name] = str(self.png('View-Opposite'))
        self.assertEqual(_current_image(self.project, name), str(self.png('View-Opposite')))
        path = self.ref_dir / 'cafe-street-view-opposite.json'
        path.write_text(json.dumps({**json.loads(path.read_text()), 'needs_regenerate': True}))
        self.assertIsNone(_current_image(self.project, name))


if __name__ == '__main__':
    unittest.main()
