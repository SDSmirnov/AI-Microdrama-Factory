"""Item 10: post glue.

10a. cutter opt-in --edge-trim <seconds> (default 0.0 = current behavior):
after a clip passes the usability + fidelity gates, head and tail are
trimmed by this amount before writing. Negative values rejected at parse
time; a window smaller than 2x trim skips the clip with a log line.
10b. env AI_ERA_LOCK (optional, empty default): when set, its sentence is
appended to SCENE CONTEXT in every clip prompt (era-drift guard).
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import RefBite, build_video_prompt
from lib.studio.cutter import run_autocut


class _StubLLM:
    """Returns a fixed passing analysis for every clip."""

    def analyze_video(self, video, prompt, schema):
        return {"is_usable": True, "fidelity_score": 5,
                "start_time": 0.0, "end_time": 4.0, "edit_notes": ""}


class EdgeTrimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())).resolve()
        self.clips = self.tmp / "clips"
        self.out = self.tmp / "out"
        self.clips.mkdir()
        (self.clips / "clip_01_001.mp4").write_bytes(b"MP4")
        meta = {"scenes": [{"scene_id": 1, "panels": [
            {"panel_index": 1, "visual_start": "", "visual_end": "",
             "motion_prompt": "", "lights_and_camera": "", "dialogue": "",
             "sound_design": "", "transition_to_next": "hard_cut"}]}]}
        self.json_path = self.tmp / "meta.json"
        self.json_path.write_text(json.dumps(meta))

        self.cuts = []
        self._orig = __import__("lib.studio.cutter", fromlist=["x"]).ffmpeg_cut
        __import__("lib.studio.cutter", fromlist=["x"]).ffmpeg_cut = \
            lambda i, o, s, e: self.cuts.append((s, e))
        self.addCleanup(setattr, __import__("lib.studio.cutter", fromlist=["x"]),
                        "ffmpeg_cut", self._orig)

    def test_zero_default_keeps_current_behavior(self):
        run_autocut(_StubLLM(), str(self.json_path), str(self.clips),
                    str(self.out))
        self.assertEqual(self.cuts, [(0.0, 4.0)])

    def test_edge_trim_folds_into_cut_window(self):
        run_autocut(_StubLLM(), str(self.json_path), str(self.clips),
                    str(self.out), edge_trim=0.3)
        self.assertEqual(self.cuts, [(0.3, 3.7)])

    def test_window_too_small_skips_clip_with_log(self):
        import logging
        logger = logging.getLogger("lib.studio.cutter")
        with self.assertLogs(logger, level=logging.WARNING) as logs:
            run_autocut(_StubLLM(), str(self.json_path), str(self.clips),
                        str(self.out), edge_trim=2.5)  # 2*2.5 >= 4.0
        self.assertEqual(self.cuts, [])
        self.assertTrue(any("edge" in o.lower() for o in logs.output))

    def test_parser_rejects_negative_edge_trim(self):
        from lib.commands.animation import register
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        register(sub)
        with self.assertRaises(SystemExit):
            parser.parse_args(["autocut", "--json", "x", "--clips-dir", "x",
                               "--out-dir", "x", "--edge-trim", "-0.5"])


class EraLockTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("AI_ERA_LOCK", None)

    def tearDown(self):
        os.environ.pop("AI_ERA_LOCK", None)
        if self._old is not None:
            os.environ["AI_ERA_LOCK"] = self._old

    def _prompt(self):
        panel = {"panel_index": 1,
                 "visual_start": "[SCALE] MS 35mm eye-level cam@[wall]",
                 "motion_intent": "He waits.", "dialogue": "",
                 "state": {"actors": []}}
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "f", "")]
        return build_video_prompt(panel, refs, [], 4)

    def test_era_lock_appended_to_scene_context(self):
        os.environ["AI_ERA_LOCK"] = "Nothing in frame is newer than 2011."
        ctx = self._prompt().split("SCENE CONTEXT:")[1].split("\n\n")[0]
        self.assertIn("Nothing in frame is newer than 2011.", ctx)

    def test_unset_leaves_scene_context_alone(self):
        ctx = self._prompt().split("SCENE CONTEXT:")[1].split("\n\n")[0]
        self.assertNotIn("2011", ctx)


class CutterFailureTests(unittest.TestCase):
    """ffmpeg and analysis failures must surface, not produce a fake report."""

    def setUp(self):
        self.tmp = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())).resolve()
        self.clips = self.tmp / "clips"
        self.out = self.tmp / "out"
        self.clips.mkdir()
        (self.clips / "clip_01_001.mp4").write_bytes(b"MP4")
        meta = {"scenes": [{"scene_id": 1, "panels": [
            {"panel_index": 1, "visual_start": "", "visual_end": "",
             "motion_prompt": "", "lights_and_camera": "", "dialogue": "",
             "sound_design": "", "transition_to_next": "hard_cut"}]}]}
        self.json_path = self.tmp / "meta.json"
        self.json_path.write_text(json.dumps(meta))

    def test_ffmpeg_nonzero_raises(self):
        import subprocess
        from unittest import mock
        from lib.studio.cutter import ffmpeg_cut

        with mock.patch("lib.studio.cutter.subprocess.run") as run:
            run.side_effect = subprocess.CalledProcessError(
                1, "ffmpeg", stderr=b"boom")
            with self.assertRaises(RuntimeError) as ctx:
                ffmpeg_cut(Path("in.mp4"), Path("out.mp4"), 0.0, 1.0)
        self.assertIn("boom", str(ctx.exception))

    def test_failed_cut_raises_and_writes_no_report(self):
        from unittest import mock

        with mock.patch("lib.studio.cutter.ffmpeg_cut",
                        side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_autocut(_StubLLM(), str(self.json_path), str(self.clips),
                            str(self.out))
        self.assertFalse((self.out / "clip_1_001_cut.json").exists())

    def test_missing_analysis_fields_raise(self):
        class _IncompleteLLM:
            def analyze_video(self, video, prompt, schema):
                return {"is_usable": True}

        with self.assertRaises(RuntimeError):
            run_autocut(_IncompleteLLM(), str(self.json_path), str(self.clips),
                        str(self.out))


if __name__ == "__main__":
    unittest.main()
