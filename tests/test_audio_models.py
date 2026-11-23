"""Audio models follow the environment: Whisper size/device/precision and the dubbing text model."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.audio import dubbing, whisper


class WhisperConfigTests(unittest.TestCase):
    def _loaded(self, **env):
        with mock.patch.dict(os.environ), mock.patch.object(whisper, 'WhisperModel') as model:
            for key in ('AI_WHISPER_MODEL', 'AI_WHISPER_DEVICE', 'AI_WHISPER_COMPUTE'):
                os.environ.pop(key, None)
            os.environ.update(env)
            whisper.load_whisper()
        return model.call_args

    def test_defaults_are_medium_on_cpu_in_int8(self):
        self.assertEqual(self._loaded(), mock.call('medium', device='cpu', compute_type='int8'))

    def test_env_selects_model_device_and_precision(self):
        self.assertEqual(self._loaded(AI_WHISPER_MODEL='large-v3', AI_WHISPER_DEVICE='cuda',
                                      AI_WHISPER_COMPUTE='float16'),
                         mock.call('large-v3', device='cuda', compute_type='float16'))

    def test_missing_package_says_how_to_install(self):
        with mock.patch.object(whisper, 'WhisperModel', None), self.assertRaisesRegex(RuntimeError, 'pip install'):
            whisper.load_whisper()


class DubbingModelTests(unittest.TestCase):
    def test_dubbing_uses_the_configured_text_model(self):
        with mock.patch.dict(os.environ, {'AI_TEXT_MODEL': 'google/gemini-x', 'GOOGLE_API_KEY': 'k'}), \
                mock.patch.object(dubbing, 'GeminiLLM') as llm:
            dubbing._default_llm()
        self.assertEqual(llm.call_args.kwargs['text_model'], 'google/gemini-x')


if __name__ == '__main__':
    unittest.main()
