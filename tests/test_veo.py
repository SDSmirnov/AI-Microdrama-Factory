"""VeoAnimator talks to the native google.genai SDK."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation import veo


def _animator(**kw):
    with mock.patch.object(veo.genai, 'Client'), tempfile.TemporaryDirectory() as d:
        return veo.VeoAnimator(api_key='k', ref_dir=Path(d), **kw)


class VeoModelIdTests(unittest.TestCase):
    def test_openrouter_prefix_is_stripped_for_native_sdk(self):
        self.assertEqual(_animator().gemini_text_model, 'gemini-4-hydrogen')

    def test_bare_id_is_kept(self):
        self.assertEqual(_animator(gemini_text_model='gemini-x').gemini_text_model, 'gemini-x')


class VeoImageTests(unittest.TestCase):
    def test_loaded_image_survives_closed_file(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'a.png'
            Image.new('RGB', (4, 4), 'red').save(path)
            img = veo._load_image(path)
        self.assertEqual(img.getpixel((0, 0)), (255, 0, 0))


class VeoPromptTests(unittest.TestCase):
    PANEL = {'visual_start': 'MS 35mm EYE cam@door', 'motion_prompt': 'Anna turns her head 30 deg',
             'dialogue': 'Anna (F): Not now.', 'hook_type': 'pivot', 'text_safe_composition': 'top third',
             'duration': 6}

    def _sent_prompt(self, end=False):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            start = Path(d) / '001_01_start.png'
            Image.new('RGB', (4, 4)).save(start)
            end_path = Path(d) / '001_01_end.png'
            if end:
                Image.new('RGB', (4, 4)).save(end_path)
            a = _animator()
            a._need_references = lambda meta, img: []
            a.client.models.generate_videos.side_effect = RuntimeError('stop')
            a.animate(start, end_path, dict(self.PANEL), 1, Path(d) / 'clips')
            return a.client.models.generate_videos.call_args.kwargs

    def test_prompt_comes_from_shared_builder_not_raw_metadata(self):
        prompt = self._sent_prompt()['prompt']
        self.assertIn('Anna turns her head 30 deg', prompt)
        self.assertIn('Not now.', prompt)
        self.assertNotIn('text_safe_composition', prompt)
        self.assertNotIn("'hook_type'", prompt)

    def test_prompt_states_the_clip_length_sent(self):
        call = self._sent_prompt(end=True)
        self.assertEqual(call['config']['duration_seconds'], 8)
        self.assertIn('8', call['prompt'].split('ACTION TIMING:')[1].split('LIGHTING:')[0])


class VeoPollingTests(unittest.TestCase):
    def test_stuck_operation_gives_up_at_ai_video_timeout(self):
        from PIL import Image
        stuck = mock.Mock(done=False)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict('os.environ', {'AI_VIDEO_TIMEOUT': '0'}), \
                mock.patch('time.sleep'), mock.patch('time.time', return_value=0.0):
            start = Path(d) / '001_01_start.png'
            Image.new('RGB', (4, 4)).save(start)
            a = _animator()
            a._need_references = lambda meta, img: []
            a.client.models.generate_videos.return_value = stuck
            a.client.operations.get.side_effect = [stuck] * 50 + [RuntimeError('polled forever')]
            out = a.animate(start, Path(d) / 'none.png', {'motion_prompt': 'x'}, 1, Path(d) / 'clips')
        self.assertIsNone(out)
        self.assertLessEqual(a.client.operations.get.call_count, 1)


class WaitForOperationTests(unittest.TestCase):
    def test_returns_the_finished_operation_after_polling(self):
        from lib.llm.gemini import wait_for_operation
        pending, finished = mock.Mock(done=False), mock.Mock(done=True)
        client = mock.Mock()
        client.operations.get.side_effect = [pending, finished]
        with mock.patch('time.sleep') as sleep:
            self.assertIs(wait_for_operation(client, pending), finished)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [10, 20])

    def test_a_hung_poll_does_not_outlive_the_deadline(self):
        import threading
        import time
        from lib.llm import gemini
        release = threading.Event()
        self.addCleanup(release.set)
        client = mock.Mock()
        client.operations.get.side_effect = lambda op: release.wait(5)
        clock = mock.Mock(time=mock.Mock(side_effect=[0, 0, 1000]), sleep=mock.Mock())
        start = time.monotonic()
        with mock.patch.object(gemini, 'time', clock), mock.patch.object(gemini, 'OPS_GET_TIMEOUT', 0.05), \
                self.assertRaises(TimeoutError):
            gemini.wait_for_operation(client, mock.Mock(done=False))
        self.assertLess(time.monotonic() - start, 2)


if __name__ == '__main__':
    unittest.main()
