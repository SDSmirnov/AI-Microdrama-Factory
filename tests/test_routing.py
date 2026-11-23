"""Provider routing for the OpenRouter text/video paths.

The lever: every Google model we might use as a judge offers a FLEX service
tier at exactly half the standard price, and OpenRouter's default routing
lands on STANDARD. ":floor" (model-slug routing variant) is a superset of
price-sorting that also makes flex endpoints eligible.

Measured effect on a QA judge call (median profile: 39,616 in + 5,724 out):
  argon   standard $0.1365 -> flex $0.0682
  3.8     standard $0.0512 -> flex $0.0256
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm.openrouter import OpenRouterLLM
from lib.llm.routing import build_routing, routing_summary


class RoutingConfigTests(unittest.TestCase):
    def test_default_is_no_routing(self):
        r = build_routing()
        self.assertIsNone(r["provider"])
        self.assertEqual(r["model_suffix"], "")
        self.assertEqual(routing_summary(r), "default routing")

    def test_sort_price(self):
        r = build_routing(sort="price")
        self.assertEqual(r["provider"], {"sort": "price"})

    def test_invalid_sort_is_ignored(self):
        r = build_routing(sort="cheap")
        self.assertIsNone(r["provider"])

    def test_invalid_suffix_is_ignored(self):
        r = build_routing(model_suffix="turbo")
        self.assertEqual(r["model_suffix"], "")

    def test_order_is_split_on_commas(self):
        r = build_routing(order="google-ai-studio/flex, google-vertex")
        self.assertEqual(r["provider"]["order"],
                         ["google-ai-studio/flex", "google-vertex"])

    def test_floor_suffix_and_price_sort_together(self):
        r = build_routing(sort="price", model_suffix="floor")
        self.assertEqual(r["provider"], {"sort": "price"})
        self.assertEqual(r["model_suffix"], "floor")

    def test_provider_order_alone_keeps_sort_absent(self):
        r = build_routing(order="google-ai-studio/flex")
        self.assertNotIn("sort", r["provider"])


_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")


class _FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RoutingApplicationTests(unittest.TestCase):
    def _llm(self, **env):
        for k in ("AI_ROUTING_SORT", "AI_ROUTING_ORDER",
                  "AI_ROUTING_MODEL_SUFFIX"):
            os.environ.pop(k, None)
        os.environ.update(env)
        llm = OpenRouterLLM(api_key="sk-test", text_model="google/gemini-4-argon",
                             image_model="")
        return llm

    def tearDown(self):
        for k in ("AI_ROUTING_SORT", "AI_ROUTING_ORDER",
                  "AI_ROUTING_MODEL_SUFFIX"):
            os.environ.pop(k, None)

    def test_model_name_appends_floor_suffix(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        self.assertEqual(llm._model_name("google/gemini-4-argon"),
                         "google/gemini-4-argon:floor")

    def test_model_name_bare_id_gets_prefix_then_suffix(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        self.assertEqual(llm._model_name("gemini-4-argon"),
                         "google/gemini-4-argon:floor")

    def test_model_name_without_suffix_is_unchanged(self):
        llm = self._llm()
        self.assertEqual(llm._model_name("google/gemini-4-argon"),
                         "google/gemini-4-argon")

    def test_existing_suffix_is_not_doubled(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        self.assertEqual(llm._model_name("google/gemini-4-argon:floor"),
                         "google/gemini-4-argon:floor")

    # -- the suffix must NOT reach the image model -------------------
    # Measured 2026-11-12: "google/gemini-nano-banana-2.1:floor" -> 404
    # "No model found" on the OpenRouter Image API. The flex service tier
    # exists for text models only; the routing variant is a text-path
    # concept, so _model_name takes an explicit suffix flag and the image
    # call sites pass suffix=False.

    def test_image_model_never_gets_the_suffix(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        self.assertEqual(
            llm._model_name("google/gemini-nano-banana-2.1", suffix=False),
            "google/gemini-nano-banana-2.1")

    def test_text_model_still_gets_the_suffix(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        self.assertEqual(
            llm._model_name("google/gemini-4-argon", suffix=True),
            "google/gemini-4-argon:floor")

    def test_image_payload_uses_the_unsuffixed_model(self):
        llm = self._llm(AI_ROUTING_MODEL_SUFFIX="floor")
        llm.image_model = "google/gemini-nano-banana-2.1"
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(json or {})
            return _FakeResponse({"data": [{"b64_json": "AA=="}]})

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = fake_post
        try:
            llm._make_image_via_api("a red cube", refs=[],
                                    aspect_ratio="9:16", image_size="1K")
        except Exception:
            pass
        finally:
            mod.requests.post = original
        self.assertEqual(captured.get("model"),
                         "google/gemini-nano-banana-2.1")
        self.assertNotIn(":floor", captured.get("model", ""))

    def test_payload_gains_provider_when_configured(self):
        llm = self._llm(AI_ROUTING_SORT="price")
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(json or {})
            return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = fake_post
        try:
            llm.make_json("hi", schema={"type": "object"})
        finally:
            mod.requests.post = original
        self.assertEqual(captured.get("provider"), {"sort": "price"})

    def test_payload_has_no_provider_by_default(self):
        llm = self._llm()
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(json or {})
            return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = fake_post
        try:
            llm.make_json("hi", schema={"type": "object"})
        finally:
            mod.requests.post = original
        self.assertNotIn("provider", captured)

    def test_text_request_forwards_timeout(self):
        llm = self._llm()
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["timeout"] = timeout
            return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = fake_post
        try:
            llm.make_json("hi", schema={"type": "object"})
        finally:
            mod.requests.post = original
        self.assertEqual(captured["timeout"], 300)

    def test_video_payload_gains_provider(self):
        llm = self._llm(AI_ROUTING_SORT="price")
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(json or {})
            return _FakeResponse({"id": "job-1", "polling_url": "u",
                                  "status": "completed", "unsigned_urls": []})

        import lib.llm.openrouter as mod
        original = mod.requests.post
        mod.requests.post = fake_post
        try:
            llm.generate_video(prompt="p", start_image=_TINY_PNG, duration=4,
                               reference_images=None)
        except Exception:
            pass  # the fake never yields a usable content URL; we only
                  # assert on the submitted payload
        finally:
            mod.requests.post = original
        self.assertEqual(captured.get("provider"), {"sort": "price"})


if __name__ == "__main__":
    unittest.main()
