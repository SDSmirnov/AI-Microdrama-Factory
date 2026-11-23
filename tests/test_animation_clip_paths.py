"""Animators and autocut must agree on clip filenames.

Panel images are ``{scene:03d}_{panel:02d}_{frame}.png``; clips are
``clip_{scene:02d}_{panel:03d}.mp4`` (the pattern ``studio.cutter`` reads).
Regression guard for the Veo/Grok single-panel path, which used to emit
``clip_001_01.mp4`` and was silently skipped by ``autocut``.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.base import clip_path_for_panel


class ClipPathTests(unittest.TestCase):
    def test_static_frame_maps_to_canonical_clip_name(self):
        out = clip_path_for_panel(Path("panels/001_01_static.png"), Path("clips"))
        self.assertEqual(out, Path("clips/clip_01_001.mp4"))

    def test_start_and_end_frames_share_the_same_clip_name(self):
        out_dir = Path("clips")
        start = clip_path_for_panel(Path("panels/012_07_start.png"), out_dir)
        end = clip_path_for_panel(Path("panels/012_07_end.png"), out_dir)
        self.assertEqual(start, Path("clips/clip_12_007.mp4"))
        self.assertEqual(start, end)

    def test_matches_autocut_pattern(self):
        scene_id, panel_id = 3, 12
        expected = f"clip_{scene_id:02d}_{panel_id:03d}.mp4"
        out = clip_path_for_panel(Path(f"panels/{scene_id:03d}_{panel_id:02d}_static.png"),
                                  Path("clips"))
        self.assertEqual(out.name, expected)

    def test_non_standard_stem_falls_back_to_legacy_id(self):
        out = clip_path_for_panel(Path("panels/extra_shot_static.png"), Path("clips"))
        self.assertEqual(out.name, "clip_extra_shot.mp4")


if __name__ == "__main__":
    unittest.main()
