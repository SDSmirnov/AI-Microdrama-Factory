"""Unit tests for the video payload builder (Item 1, GROK-VIDEO-PLAN).

No HTTP: generate_video()'s payload assembly is a pure function, so the
transport-level rules (reference mapping, last_frame pin, resolution clamp)
are checked without an API key or network.
"""
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm.openrouter import build_video_payload


def _png_data_url(tag: bytes = b"a") -> str:
    return "data:image/png;base64," + base64.b64encode(b"PNG" + tag).decode("ascii")


class BuildVideoPayloadTests(unittest.TestCase):
    def test_baseline_payload_unchanged(self):
        """No refs, no last_frame: payload matches the pre-Item-1 shape."""
        start = _png_data_url(b"start")
        payload = build_video_payload(
            prompt="P", start_image=start, duration=6, resolution="720p",
        )
        self.assertEqual(payload["model"], "x-ai/grok-imagine-video-1.5")
        self.assertEqual(payload["prompt"], "P")
        self.assertEqual(payload["duration"], 6)
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["frame_images"], [
            {"type": "image_url", "image_url": {"url": start},
             "frame_type": "first_frame"},
        ])
        self.assertNotIn("input_references", payload)
        self.assertNotIn("generate_audio", payload)
        self.assertNotIn("seed", payload)

    def test_reference_images_map_in_order(self):
        start = _png_data_url(b"0")
        ref1, ref2 = _png_data_url(b"1"), _png_data_url(b"2")
        payload = build_video_payload(
            prompt="P <IMAGE_1> <IMAGE_2>", start_image=start,
            reference_images=[ref1, ref2], resolution="720p",
        )
        refs = payload["input_references"]
        # Probe 3 (2026-11-10): frame_images + input_references is rejected
        # with 400 by the grok-imagine-video-1.5 integration, so refs mode
        # puts EVERYTHING in input_references: start first (<IMAGE_0>),
        # refs after (<IMAGE_1..N>), no frame_images key at all.
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[0]["image_url"]["url"], start)
        self.assertEqual(refs[1]["image_url"]["url"], ref1)
        self.assertEqual(refs[2]["image_url"]["url"], ref2)
        for ref in refs:
            self.assertEqual(ref["type"], "image_url")
        self.assertNotIn("frame_images", payload)

    def test_no_refs_keeps_frame_images(self):
        start = _png_data_url(b"s")
        payload = build_video_payload(
            prompt="P", start_image=start, resolution="720p",
        )
        self.assertEqual(payload["frame_images"], [
            {"type": "image_url", "image_url": {"url": start},
             "frame_type": "first_frame"},
        ])
        self.assertNotIn("input_references", payload)

    def test_reference_images_accept_paths_and_bytes(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(b"PNGref")
            f.flush()
            payload = build_video_payload(
                prompt="P", start_image=_png_data_url(),
                reference_images=[Path(f.name), b"rawpng"], resolution="720p",
            )
        self.assertEqual(len(payload["input_references"]), 3)
        for ref in payload["input_references"]:
            self.assertTrue(ref["image_url"]["url"].startswith("data:image/"))

    def test_more_than_14_references_rejected(self):
        start = _png_data_url()
        # 15 refs + start = 16 total > model cap 14 (cap counts everything).
        with self.assertRaises(ValueError):
            build_video_payload(
                prompt="P", start_image=start,
                reference_images=[_png_data_url(bytes([i])) for i in range(15)],
                resolution="720p",
            )

    def test_last_frame_dropped_in_refs_mode(self):
        # Probe 2/3 (2026-11-10): last_frame unsupported and the two fields
        # can't combine; in refs mode the pin has nowhere to go — dropped.
        start, end = _png_data_url(b"s"), _png_data_url(b"e")
        payload = build_video_payload(
            prompt="P", start_image=start, last_frame=end,
            reference_images=[_png_data_url(b"1")], resolution="720p",
        )
        self.assertNotIn("frame_images", payload)
        self.assertEqual(len(payload["input_references"]), 2)

    def test_last_frame_appended_after_first(self):
        start, end = _png_data_url(b"s"), _png_data_url(b"e")
        payload = build_video_payload(
            prompt="P", start_image=start, last_frame=end, resolution="720p",
        )
        self.assertEqual(payload["frame_images"], [
            {"type": "image_url", "image_url": {"url": start},
             "frame_type": "first_frame"},
            {"type": "image_url", "image_url": {"url": end},
             "frame_type": "last_frame"},
        ])

    def test_no_last_frame_keeps_single_entry(self):
        start = _png_data_url()
        payload = build_video_payload(
            prompt="P", start_image=start, last_frame=None, resolution="720p",
        )
        self.assertEqual(len(payload["frame_images"]), 1)

    def test_resolution_clamped_to_model_cap(self):
        start = _png_data_url()
        payload = build_video_payload(
            prompt="P", start_image=start, resolution="1080p",
        )
        self.assertEqual(payload["resolution"], "720p")

    def test_resolution_below_cap_kept(self):
        start = _png_data_url()
        payload = build_video_payload(
            prompt="P", start_image=start, resolution="480p",
        )
        self.assertEqual(payload["resolution"], "480p")

    def test_generate_audio_and_seed_passthrough(self):
        start = _png_data_url()
        payload = build_video_payload(
            prompt="P", start_image=start, resolution="720p",
            generate_audio=True, seed=21,
        )
        self.assertTrue(payload["generate_audio"])
        self.assertEqual(payload["seed"], 21)

    def test_model_override(self):
        payload = build_video_payload(
            prompt="P", start_image=_png_data_url(), resolution="720p",
            model="other/video-model",
        )
        self.assertEqual(payload["model"], "other/video-model")

    def test_aspect_ratio_passthrough(self):
        payload = build_video_payload(
            prompt="P", start_image=_png_data_url(), resolution="720p",
            aspect_ratio="9:16",
        )
        self.assertEqual(payload["aspect_ratio"], "9:16")

    def test_aspect_ratio_omitted_when_none(self):
        payload = build_video_payload(
            prompt="P", start_image=_png_data_url(), resolution="720p",
        )
        self.assertNotIn("aspect_ratio", payload)


if __name__ == "__main__":
    unittest.main()
