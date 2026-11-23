"""Room-view QA: deterministic framing checks layered on the vision rubric."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import critic
from lib.studio.artist import _anchor_visibility_block


class RoomViewAspectTests(unittest.TestCase):
    class QAStub:
        def __init__(self):
            self.prompt = ''
            self.image = None

        def analyze_image(self, image, prompt, schema=None):
            self.prompt = prompt
            self.image = image
            return {
                'consistency_score': 10,
                'geometry_score': 10,
                'needs_regeneration': False,
                'issues': [],
                'regeneration_prompt': '',
            }

    @staticmethod
    def _image(size):
        return Image.new('RGB', size, (40, 40, 40))

    def _analyze(self, view_size, expected_aspect, with_sketch=False):
        llm = self.QAStub()
        view = self._image(view_size)
        source = self._image((896, 1200))
        sketch = self._image((1024, 576)) if with_sketch else None
        try:
            return critic.analyze_room_view(
                llm=llm,
                view_img=view,
                source_views=[('View-From-Entrance', source)],
                view_suffix='View-To-Entrance',
                visual_desc='Steel room.',
                threshold=7,
                expected_aspect=expected_aspect,
                sketch_img=sketch,
            ), llm
        finally:
            view.close()
            source.close()
            if sketch is not None:
                sketch.close()

    def test_wrong_aspect_fails_geometry(self):
        result, llm = self._analyze((896, 1200), '16:9')
        self.assertLess(result['geometry_score'], 7)
        self.assertTrue(result['needs_regeneration'])
        self.assertTrue(
            any('aspect ratio' in issue.lower() for issue in result['issues'])
        )
        self.assertIn('EXPECTED FRAMING', llm.prompt)
        self.assertIn('16:9', result['regeneration_prompt'])

    def test_matching_aspect_keeps_llm_score(self):
        result, _ = self._analyze((1024, 576), '16:9')
        self.assertEqual(result['geometry_score'], 10)
        self.assertFalse(result['needs_regeneration'])
        self.assertEqual(result['issues'], [])

    def test_no_expected_aspect_skips_check(self):
        result, _ = self._analyze((896, 1200), None)
        self.assertEqual(result['geometry_score'], 10)
        self.assertFalse(result['needs_regeneration'])

    def test_sketch_is_geometry_only_truth(self):
        result, llm = self._analyze((1024, 576), '16:9', with_sketch=True)
        self.assertEqual(result['geometry_score'], 10)
        self.assertIn('GEOMETRY SKETCH', llm.prompt)
        self.assertIn('Image 3 is "View-To-Entrance"', llm.prompt)
        self.assertIn('must NOT be reported as missing', llm.prompt)
        # source, sketch, evaluated — the sketch sits between truth and candidate
        images = [item for item in llm.image if not isinstance(item, str)]
        self.assertEqual(len(images), 3)
        self.assertEqual(images[1].size, (1024, 576))

    def test_outdoor_sketch_is_a_station_view_without_a_wall_cut(self):
        llm, img = self.QAStub(), self._image((48, 27))
        critic.analyze_room_view(llm=llm, view_img=img, source_views=[('View-Primary', img)],
                                 view_suffix='View-Ortho-Opposite', visual_desc='Street.', sketch_img=img)
        self.assertIn('same camera station as View-Primary', llm.prompt)
        self.assertIn('Facades: material', llm.prompt)
        self.assertNotIn('Wall views are cut', llm.prompt)
        self.assertNotIn('Ceiling:', llm.prompt)

    def test_anchor_block_insets_the_room_camera(self):
        anchors = {
            'room_m': [5.0, 8.0],
            'objects': [{
                'id': 'rack-near-left-wall', 'label': 'Rack',
                'x': 0.05, 'y': 0.5, 'z': 0.5,
                'width_x': 0.05, 'depth_y': 0.5,
            }],
        }
        block = _anchor_visibility_block(
            anchors, 'View-From-Left-Wall', camera_inset_m=critic.WALL_INSET_M
        )
        self.assertIn('cut 0.5 m inside the camera wall', block)
        self.assertIn('MUST NOT APPEAR', block)
        self.assertNotIn('OBJECTS VISIBLE FROM THIS CAMERA ANGLE', block)


if __name__ == '__main__':
    unittest.main()
