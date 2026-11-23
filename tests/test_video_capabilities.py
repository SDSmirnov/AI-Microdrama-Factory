"""Video model capability envelopes — what each model will actually accept.

The repo was written when video models did simple I2V: one start frame,
optionally an end frame, a fixed ~6 s clip. The models moved on, and two of
the old assumptions are now actively wrong:

1. DURATION. The code clamped to MAX_DURATION=15. But reference-to-video
   is capped at 10 s. MEASURED: an 11 s request with input_references on
   x-ai/grok-imagine-video returns
       HTTP 400 "Duration 11s exceeds the maximum allowed for
       reference-to-video, which is 10s."
   Our transport is refs-only, so 10 s was the real ceiling all along and
   a 12-15 s panel would have 400'd mid-run.

2. REFERENCES. MEASURED: `input_references is not supported for this
   model` (HTTP 400) on x-ai/grok-imagine-video-1.5-lite, while
   frame_images with first_frame works. Lite is a first-frame-only model
   — it cannot carry our character/location reference library, which is
   the whole point of the Item 2 assembler.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.capabilities import (MODELS, caps_for,
                                        plan_clip)


class ModelTableTests(unittest.TestCase):
    def test_grok_15_takes_references(self):
        c = caps_for("x-ai/grok-imagine-video-1.5")
        self.assertTrue(c.supports_input_references)
        self.assertEqual(c.min_seconds, 1)
        self.assertEqual(c.max_seconds, 15)
        self.assertIn("1080p", c.resolutions)

    def test_lite_does_not_take_references(self):
        c = caps_for("x-ai/grok-imagine-video-1.5-lite")
        self.assertFalse(c.supports_input_references)
        self.assertTrue(c.supports_frame_images)

    def test_seedance_is_the_only_one_with_last_frame(self):
        with_last = [c.slug for c in MODELS.values() if c.supports_last_frame]
        self.assertEqual(with_last, ["bytedance/seedance-2.0"])

    def test_bare_id_resolves(self):
        self.assertEqual(caps_for("grok-imagine-video-1.5").slug,
                         "x-ai/grok-imagine-video-1.5")

    def test_unknown_model_gets_a_safe_envelope(self):
        c = caps_for("some/unknown-video-model")
        self.assertEqual(c.max_seconds, 10)
        self.assertEqual(c.ref_max_seconds, 10)
        self.assertTrue(c.supports_input_references)


class ClampTests(unittest.TestCase):
    def test_reference_mode_cap_is_per_model(self):
        """The 10 s cap is the OLDER model's. x.ai's docs give 15 s for
        grok-imagine-video-1.5 - and the MEASURED 400 confirms OpenRouter
        enforces the older model's documented 10 s."""
        old = caps_for("x-ai/grok-imagine-video")
        self.assertEqual(old.ref_max_seconds, 10)
        self.assertEqual(old.clamp_seconds(11, using_references=True), 10)
        new = caps_for("x-ai/grok-imagine-video-1.5")
        self.assertEqual(new.ref_max_seconds, 15)
        self.assertEqual(new.clamp_seconds(15, using_references=True), 15)

    def test_image_mode_runs_to_fifteen(self):
        c = caps_for("x-ai/grok-imagine-video-1.5")
        self.assertEqual(c.clamp_seconds(15, using_references=False), 15)

    def test_short_durations_pass_through(self):
        c = caps_for("x-ai/grok-imagine-video-1.5")
        self.assertEqual(c.clamp_seconds(4, using_references=True), 4)
        self.assertEqual(c.clamp_seconds(6, using_references=True), 6)

    def test_below_minimum_is_raised(self):
        c = caps_for("bytedance/seedance-2.0")
        self.assertEqual(c.clamp_seconds(1, using_references=True), 4)


class PlanClipTests(unittest.TestCase):
    def test_a_15s_refs_request_is_allowed_on_1_5(self):
        """1.5 allows 15 s in reference mode per the vendor doc."""
        plan = plan_clip("x-ai/grok-imagine-video-1.5", 15, "720p", "9:16",
                         n_reference_images=4)
        self.assertEqual(plan["duration"], 15)
        self.assertEqual(plan["notes"], [])

    def test_an_11s_refs_request_becomes_10s_on_the_older_model(self):
        """MEASURED: 11 s with input_references on x-ai/grok-imagine-video
        returns HTTP 400 "Duration 11s exceeds the maximum allowed for
        reference-to-video, which is 10s."."""
        plan = plan_clip("x-ai/grok-imagine-video", 11, "720p", "9:16",
                         n_reference_images=4)
        self.assertEqual(plan["duration"], 10)
        self.assertTrue(any("10 s" in n for n in plan["notes"]))

    def test_refs_are_dropped_for_lite(self):
        plan = plan_clip("x-ai/grok-imagine-video-1.5-lite", 6, "720p", "9:16",
                         n_reference_images=4)
        self.assertFalse(plan["using_references"])
        self.assertEqual(plan["n_reference_images"], 0)
        self.assertTrue(any("input_references" in n for n in plan["notes"]))
        # and the duration cap relaxes, because it is no longer ref mode
        self.assertEqual(plan["duration"], 6)

    def test_lite_can_still_do_15s_in_image_mode(self):
        plan = plan_clip("x-ai/grok-imagine-video-1.5-lite", 15, "720p", "9:16",
                         n_reference_images=0)
        self.assertEqual(plan["duration"], 15)

    def test_unsupported_resolution_falls_back(self):
        plan = plan_clip("x-ai/grok-imagine-video", 6, "1080p", "9:16",
                         n_reference_images=2)
        self.assertEqual(plan["resolution"], "720p")
        self.assertTrue(any("resolution" in n for n in plan["notes"]))

    def test_last_frame_is_dropped_when_unsupported(self):
        plan = plan_clip("x-ai/grok-imagine-video-1.5", 6, "720p", "9:16",
                         n_reference_images=2, wants_last_frame=True)
        self.assertFalse(plan["wants_last_frame"])

    def test_last_frame_is_kept_for_seedance(self):
        plan = plan_clip("bytedance/seedance-2.0", 6, "720p", "9:16",
                         n_reference_images=2, wants_last_frame=True)
        self.assertTrue(plan["wants_last_frame"])

    def test_a_normal_request_produces_no_notes(self):
        plan = plan_clip("x-ai/grok-imagine-video-1.5", 6, "720p", "9:16",
                         n_reference_images=3)
        self.assertEqual(plan["notes"], [])
        self.assertEqual(plan["duration"], 6)


class CostEstimateTests(unittest.TestCase):
    def test_clip_cost_matches_the_measured_probe(self):
        """MEASURED 2026-11-12: 3 s 480p with one reference image on
        x-ai/grok-imagine-video cost $0.152 = 3 x $0.05 + 1 x $0.002."""
        from lib.animation.capabilities import estimate_clip_cost
        cost = estimate_clip_cost("x-ai/grok-imagine-video", 3, "480p", 1)
        self.assertAlmostEqual(cost, 0.152, places=6)

    def test_first_frame_counts_as_an_input_image(self):
        """The models charge per image INPUT, not per reference - so the
        first frame is billed too."""
        from lib.animation.capabilities import estimate_clip_cost
        with_frame = estimate_clip_cost("x-ai/grok-imagine-video-1.5", 4,
                                        "480p", 4)
        without = estimate_clip_cost("x-ai/grok-imagine-video-1.5", 4,
                                     "480p", 3)
        self.assertAlmostEqual(with_frame - without, 0.01, places=6)

    def test_unpriced_resolution_raises(self):
        from lib.animation.capabilities import estimate_clip_cost
        with self.assertRaises(ValueError):
            estimate_clip_cost("bytedance/seedance-2.0", 5, "4K", 1)

    def test_older_grok_is_cheaper_than_1_5(self):
        from lib.animation.capabilities import estimate_episode_cost
        panels = [6] * 25 + [4] * 15 + [5] * 5   # the CRAB episode
        old = estimate_episode_cost("x-ai/grok-imagine-video", panels,
                                    "480p", 2.58)
        new = estimate_episode_cost("x-ai/grok-imagine-video-1.5", panels,
                                    "480p", 2.58)
        self.assertLess(old["total"], new["total"])

    def test_episode_per_minute_is_sane(self):
        from lib.animation.capabilities import estimate_episode_cost
        e = estimate_episode_cost("x-ai/grok-imagine-video-1.5",
                                  [6] * 25 + [4] * 15 + [5] * 5, "720p", 2.58)
        self.assertAlmostEqual(e["seconds"], 235)
        self.assertAlmostEqual(e["per_minute"], e["total"] / (235 / 60))


class AnimatorClampTests(unittest.TestCase):
    """The animator's own clamp must respect the reference-mode cap."""

    def test_clamp_respects_the_refs_cap(self):
        from lib.animation.grok_openrouter import _clamp_duration
        # the default model is grok-imagine-video-1.5: 15 s in reference mode
        self.assertEqual(_clamp_duration(15), 15)
        self.assertEqual(_clamp_duration(6), 6)
        self.assertEqual(_clamp_duration(15, using_references=False), 15)
        # the older model's documented cap is enforced
        self.assertEqual(
            _clamp_duration(15, model="x-ai/grok-imagine-video"), 10)

    def test_garbage_duration_falls_back(self):
        from lib.animation.grok_openrouter import _clamp_duration
        self.assertEqual(_clamp_duration("not-a-number"), 6)


if __name__ == "__main__":
    unittest.main()
