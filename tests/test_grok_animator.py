"""GrokAnimator (xai_sdk) sends its own settings and each panel's duration."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation import grok


class _Video:
    def __init__(self):
        self.calls = []

    async def generate(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(url='https://cdn/x.mp4')


class GrokAnimatorParamsTests(unittest.TestCase):
    def _send(self, animator, meta):
        client = SimpleNamespace(video=_Video())
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / '001_01_static.png'
            img.write_bytes(b'png')
            task = animator._task(meta, img, Path(d) / 'clip.mp4')
            asyncio.run(grok._generate_batch(client, [task], animator.model, animator.aspect_ratio, animator.resolution))
        return client.video.calls[0]

    def test_constructor_settings_reach_the_api(self):
        a = grok.GrokAnimator(api_key='k', model='grok-x', aspect_ratio='16:9', resolution='480p')
        call = self._send(a, {'motion_prompt': 'go'})
        self.assertEqual((call['model'], call['aspect_ratio'], call['resolution']),
                         ('grok-x', '16:9', '480p'))

    def test_panel_duration_wins_and_is_clamped(self):
        a = grok.GrokAnimator(api_key='k', duration=6)
        self.assertEqual(self._send(a, {'duration': 4})['duration'], 4)
        self.assertEqual(self._send(a, {'duration': 30})['duration'], 15)  # image-to-video cap, no refs
        self.assertEqual(self._send(a, {})['duration'], 6)


    def test_prompt_comes_from_shared_builder(self):
        a = grok.GrokAnimator(api_key='k')
        prompt = self._send(a, {'motion_prompt': 'Anna turns her head 30 deg', 'duration': 4})['prompt']
        self.assertIn('Anna turns her head 30 deg', prompt)
        self.assertNotIn('Filming Action Movie', prompt)
        self.assertIn('4', prompt.split('ACTION TIMING:')[1].split('LIGHTING:')[0])


if __name__ == '__main__':
    unittest.main()
