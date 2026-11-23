"""Seed handling: a render must be a NEW sample, not a near-duplicate.

MEASURED 2026-11-12 (google/gemini-nano-banana-2.1, chat path, 1K, 1:1):
    temperature 1.0, top_p 0.95, seed 21:
        call 1 -> md5 18994ae183e8
        call 2 -> md5 a962f670b535     <- SAME seed, DIFFERENT image

The provider treats `seed` as a HINT, not a determinism guarantee. The old
code sent a fixed AI_SEED on every render and every edit, so the regen path
(lib/studio/editor.py `_regenerate_t2i`) could return a near-duplicate of
the panel it was replacing.

These tests lock in the fix:
  - successive calls get different seeds
  - the seed does not affect price (nothing about the payload changes
    except the seed value)
  - AI_SEED_STRICT=1 restores the old fixed-seed behaviour
  - the counter is thread-safe (the animator renders panels concurrently)
"""
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm.seeds import SeedCounter, base_seed


class SeedCounterTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("AI_SEED", None)
        os.environ.pop("AI_SEED_STRICT", None)

    def tearDown(self):
        os.environ.pop("AI_SEED", None)
        os.environ.pop("AI_SEED_STRICT", None)

    def test_base_seed_defaults_to_21(self):
        self.assertEqual(base_seed(), 21)

    def test_base_seed_reads_env(self):
        os.environ["AI_SEED"] = "77"
        self.assertEqual(base_seed(), 77)

    def test_base_seed_survives_garbage(self):
        os.environ["AI_SEED"] = "not-a-number"
        self.assertEqual(base_seed(), 21)

    def test_successive_seeds_differ(self):
        c = SeedCounter()
        seeds = [c.next() for _ in range(5)]
        self.assertEqual(len(set(seeds)), 5)

    def test_seeds_start_from_the_base(self):
        c = SeedCounter()
        self.assertEqual(c.base, 21)
        self.assertEqual(c.next(), 22)

    def test_strict_mode_returns_the_base_seed(self):
        os.environ["AI_SEED_STRICT"] = "1"
        c = SeedCounter()
        self.assertEqual([c.next() for _ in range(3)], [21, 21, 21])

    def test_counter_is_thread_safe(self):
        c = SeedCounter()
        seen = []
        lock = threading.Lock()

        def worker():
            for _ in range(20):
                s = c.next()
                with lock:
                    seen.append(s)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(seen)), 160)


class SeedInPayloadTests(unittest.TestCase):
    """The seed must actually reach the request payload."""

    def setUp(self):
        os.environ.pop("AI_SEED", None)
        os.environ.pop("AI_SEED_STRICT", None)
        os.environ.pop("AI_ROUTING_MODEL_SUFFIX", None)

    def tearDown(self):
        for k in ("AI_SEED", "AI_SEED_STRICT", "AI_ROUTING_MODEL_SUFFIX"):
            os.environ.pop(k, None)

    def test_chat_image_payload_carries_a_varying_seed(self):
        from lib.llm.openrouter import OpenRouterLLM
        llm = OpenRouterLLM(api_key="sk-test", text_model="gpt-x",
                             image_model="google/gemini-nano-banana-2.1")
        captured = []

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"images": [
                    {"image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}}]}

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = lambda url, *a, **k: (
            captured.append(k.get("json")), _Resp())[1]
        try:
            llm._call_chat_image([{"type": "text", "text": "x"}], "9:16", "1K", 0.45)
            llm._call_chat_image([{"type": "text", "text": "x"}], "9:16", "1K", 0.45)
        finally:
            mod.requests.post = original

        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0]["seed"], captured[1]["seed"])

    def test_edit_image_payload_carries_a_varying_seed(self):
        from lib.llm.openrouter import OpenRouterLLM
        llm = OpenRouterLLM(api_key="sk-test", text_model="gpt-x",
                             image_model="google/gemini-nano-banana-2.1")
        captured = []

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"images": [
                    {"image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}}]}

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = lambda url, *a, **k: (
            captured.append(k.get("json")), _Resp())[1]
        try:
            llm.edit_image(src_img=b"\x89PNG\r\n\x1a\n", prompt="fix")
            llm.edit_image(src_img=b"\x89PNG\r\n\x1a\n", prompt="fix")
        finally:
            mod.requests.post = original

        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0]["seed"],
                            captured[1]["seed"])

    def test_image_api_payload_carries_a_seed(self):
        from lib.llm.openrouter import OpenRouterLLM
        llm = OpenRouterLLM(api_key="sk-test", text_model="gpt-x",
                             image_model="google/gemini-nano-banana-2.1")
        captured = []

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"b64_json": "iVBORw0KGgo="}]}

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = lambda url, *a, **k: (
            captured.append(k.get("json")), _Resp())[1]
        try:
            llm._make_image_via_api("x", refs=[], aspect_ratio="9:16",
                                    image_size="1K")
        finally:
            mod.requests.post = original
        self.assertIn("seed", captured[0])


class PanelResolutionTests(unittest.TestCase):
    """The panel render size must follow config, not a hardcoded 1K."""

    def setUp(self):
        os.environ.pop("AI_PANEL_IMAGE_SIZE", None)

    def tearDown(self):
        os.environ.pop("AI_PANEL_IMAGE_SIZE", None)

    def test_follows_config(self):
        from lib.studio.artist import _panel_image_size
        self.assertEqual(
            _panel_image_size({"image_generation": {"image_size": "2K"}}), "2K")
        self.assertEqual(
            _panel_image_size({"image_generation": {"image_size": "1K"}}), "1K")

    def test_defaults_to_2k_when_config_is_silent(self):
        from lib.studio.artist import _panel_image_size
        self.assertEqual(_panel_image_size({}), "2K")

    def test_env_override_wins(self):
        from lib.studio.artist import _panel_image_size
        os.environ["AI_PANEL_IMAGE_SIZE"] = "4K"
        self.assertEqual(
            _panel_image_size({"image_generation": {"image_size": "1K"}}), "4K")


if __name__ == "__main__":
    unittest.main()
