"""generate_sfx reports an ElevenLabs failure through logging, not stdout."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.audio import tts


class SfxFailureTests(unittest.TestCase):
    def test_a_failed_call_is_logged_as_an_error_and_returns_false(self):
        with mock.patch.object(tts, '_eleven_client', side_effect=RuntimeError('quota')), \
                self.assertLogs(tts.__name__, 'ERROR') as logs:
            self.assertFalse(tts.generate_sfx('door slam', 2.0, Path('x.mp3')))
        self.assertIn('quota', logs.output[0])


if __name__ == '__main__':
    unittest.main()
