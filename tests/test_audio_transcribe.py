"""Audio-only input support for the Whisper transcription pipeline.

Regression guards for two bugs:
  1. `from moviepy.editor import VideoFileClip` fails on moviepy 2.x (the
     `editor` module was removed) → the code misreported "moviepy not installed".
  2. The pipeline only accepted video files; a plain .wav/.mp3 input raised
     the same misleading error even with moviepy installed.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest import mock

from lib.audio import dubbing
from lib.audio.dubbing import (
    VideoFileClip,
    _extract_audio_track,
    _has_video_stream,
    _media_duration,
)


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


class TestMoviepyImport(unittest.TestCase):
    def test_moviepy_importable(self):
        self.assertIsNotNone(
            VideoFileClip,
            "moviepy could not be imported — transcription of video input is broken",
        )


class TestAudioOnlyInput(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_wav_has_no_video_stream(self):
        wav = _write_wav(self.tmp / "sample.wav")
        self.assertFalse(_has_video_stream(str(wav)))

    def test_wav_duration(self):
        wav = _write_wav(self.tmp / "sample.wav", seconds=2.0)
        self.assertAlmostEqual(_media_duration(str(wav)), 2.0, places=2)

    def test_wav_used_directly(self):
        wav = _write_wav(self.tmp / "sample.wav", seconds=1.0)
        out_wav = self.tmp / "temp_source.wav"
        path, duration = _extract_audio_track(str(wav), str(out_wav))
        self.assertEqual(path, str(wav))
        self.assertAlmostEqual(duration, 1.0, places=2)
        self.assertFalse(out_wav.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_non_wav_audio_is_transcoded(self):
        wav = _write_wav(self.tmp / "sample.wav", seconds=1.0)
        mp3 = self.tmp / "sample.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(wav), str(mp3)],
            check=True, capture_output=True,
        )
        out_wav = self.tmp / "temp_source.wav"
        path, duration = _extract_audio_track(str(mp3), str(out_wav))
        self.assertEqual(path, str(out_wav))
        self.assertTrue(out_wav.exists())
        self.assertAlmostEqual(duration, 1.0, delta=0.2)


class TestTempWavCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _transcribe(self, src, model):
        temp_wav = self.tmp / "temp_source.wav"
        def extract(source, temp):
            if source.endswith(".wav"):
                return source, 1.0
            _write_wav(Path(temp))
            return temp, 1.0
        with mock.patch.object(dubbing, "_extract_audio_track", side_effect=extract), \
                mock.patch.object(dubbing, "load_whisper", return_value=model):
            dubbing.transcribe_video(str(src), str(self.tmp / "cache.json"), str(temp_wav))
        return temp_wav

    def _model(self):
        model = mock.Mock()
        def segments():
            yield mock.Mock(start=0.0, end=1.0, text="hi", words=[])
        model.transcribe.return_value = (segments(), mock.Mock(language="en"))
        return model

    def test_extracted_wav_is_removed_after_transcription(self):
        src = self.tmp / "clip.mp4"
        src.write_bytes(b"x")
        self.assertFalse(self._transcribe(src, self._model()).exists())

    def test_input_wav_is_kept(self):
        src = _write_wav(self.tmp / "input.wav")
        self._transcribe(src, self._model())
        self.assertTrue(src.exists())


if __name__ == "__main__":
    unittest.main()
