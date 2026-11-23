"""Dubbing must fail instead of exporting a silent track with a 'Done' log."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.audio import dubbing


class _BrokenLLM:
    def make_json(self, prompt, schema=None):
        return "not a list of splits"


SEGMENTS = [{'start': 0.0, 'end': 1.0, 'original_text': 'Hello there',
             'words': [{'word': 'Hello', 'start': 0.0, 'end': 0.5},
                       {'word': 'there', 'start': 0.5, 'end': 1.0}]}]


class TranslationFailureTests(unittest.TestCase):
    def test_unparseable_translation_raises(self):
        with self.assertRaisesRegex(RuntimeError, 'translation'):
            dubbing.analyze_and_translate(SEGMENTS, llm=_BrokenLLM())


class SilentTrackTests(unittest.TestCase):
    def test_no_synthesized_segment_raises(self):
        plan = [{**SEGMENTS[0], 'ru_text': 'Привет', 'voice_type': 'narrator', 'tone': 'neutral'}]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(dubbing, 'generate_audio_segment', lambda *a, **k: False):
                with self.assertRaisesRegex(RuntimeError, 'silent track'):
                    dubbing.assemble_audio(plan, 1.0, Path(tmp) / 'seg', llm=object())


if __name__ == '__main__':
    unittest.main()
