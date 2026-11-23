"""Ducking lowers only the padded speech regions and reports failures as exceptions."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydub.generators import Sine

from lib.audio import ducking


def _tone(ms):
    return Sine(440).to_audio_segment(duration=ms).set_channels(1)


class ApplyDuckingTests(unittest.TestCase):
    def test_only_padded_regions_are_lowered(self):
        orig = _tone(3000)
        out = ducking.apply_ducking(orig, [(1000, 1500)], duck_db=-20, fade_ms=0, padding_ms=100)
        self.assertEqual(len(out), len(orig))
        self.assertAlmostEqual(out[:850].dBFS, orig[:850].dBFS, places=1)
        self.assertAlmostEqual(out[950:1550].dBFS, orig[950:1550].dBFS - 20, delta=0.5)
        self.assertAlmostEqual(out[1700:].dBFS, orig[1700:].dBFS, places=1)


class RunDuckingErrorTests(unittest.TestCase):
    def test_unreadable_input_raises_instead_of_exiting(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                ducking.run_ducking(str(Path(d) / 'missing.mp4'), str(Path(d) / 'missing.mp3'), str(Path(d) / 'o.mp3'))


if __name__ == '__main__':
    unittest.main()
