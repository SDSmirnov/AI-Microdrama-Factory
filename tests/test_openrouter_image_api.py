"""OpenRouter Image API support in the OpenRouter backend.

Several image models on OpenRouter (bytedance-seed/seedream-5-0-flash,
minimax/minimax-h3-image, ...) are served ONLY by POST /api/v1/images —
the chat/completions endpoint returns 404 for them. The production
pipeline (make refs -> panel-by-panel-with-qa) calls llm.make_image() and
llm.edit_image(), so the backend must be able to route to the Image API.

Tests cover: payload shape, refs -> input_references conversion, the
source image leading the refs on an edit, chat-first with Image-API
fallback, and the forced-backend switch.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm.openrouter import OpenRouterLLM


def _llm(image_model="bytedance-seed/seedream-5-0-flash", **kw):
    return OpenRouterLLM(api_key="k", text_model="google/gemini-4-argon",
                         image_model=image_model, video_model="", **kw)


class ImageApiPayloadTests(unittest.TestCase):
    def setUp(self):
        self.llm = _llm()
        self.captured = {}

        def fake_post(payload):
            self.captured.update(payload)
            return {"data": [{"b64_json": "aGk=", "media_type": "image/png"}],
                    "usage": {"cost": 0.018}}

        self.llm._post_image_api = fake_post

    def test_make_image_payload_shape(self):
        self.llm._make_image_via_api("PROMPT", refs=[], aspect_ratio="9:16",
                                      image_size="1K")
        p = self.captured
        self.assertEqual(p["model"], "bytedance-seed/seedream-5-0-flash")
        self.assertEqual(p["prompt"], "PROMPT")
        self.assertEqual(p["aspect_ratio"], "9:16")
        self.assertEqual(p["resolution"], "1K")
        self.assertEqual(p["n"], 1)
        self.assertNotIn("input_references", p)

    def test_refs_become_input_references_and_text_appends_to_prompt(self):
        img = {"type": "image_url",
               "image_url": {"url": "data:image/png;base64,AAAA"}}
        txt = {"type": "text", "text": "REF DESCRIPTION"}
        self.llm._make_image_via_api("PROMPT", refs=[img, txt],
                                      aspect_ratio="9:16", image_size="1K")
        p = self.captured
        self.assertEqual(len(p["input_references"]), 1)
        self.assertEqual(p["input_references"][0]["type"], "image_url")
        self.assertIn("REF DESCRIPTION", p["prompt"])

    def test_edit_puts_source_first_then_refs(self):
        src = {"type": "image_url",
               "image_url": {"url": "data:image/png;base64,SOURCE"}}
        ref = {"type": "image_url",
               "image_url": {"url": "data:image/png;base64,REF"}}
        self.llm._make_image_via_api("PROMPT", refs=[src, ref],
                                      aspect_ratio="9:16", image_size="1K")
        urls = [r["image_url"]["url"] for r in
                self.captured["input_references"]]
        self.assertEqual(urls[0], "data:image/png;base64,SOURCE")
        self.assertIn("data:image/png;base64,REF", urls)

    def test_response_bytes_decoded(self):
        out = self.llm._make_image_via_api("PROMPT", refs=[],
                                            aspect_ratio="9:16",
                                            image_size="1K")
        self.assertEqual(out, b"hi")


class ImageApiRoutingTests(unittest.TestCase):
    def test_chat_404_falls_back_to_image_api(self):
        llm = _llm()
        calls = {"chat": 0, "api": 0}

        def fake_chat(*a, **kw):
            calls["chat"] += 1
            raise RuntimeError("404 Client Error: Not Found for url: "
                               "https://openrouter.ai/api/v1/chat/completions")

        def fake_api(payload):
            calls["api"] += 1
            return {"data": [{"b64_json": "aGk="}],
                    "usage": {"cost": 0.018}}

        llm._call_chat_image = fake_chat
        llm._post_image_api = fake_api
        out = llm.make_image("P", refs=[], aspect_ratio="9:16",
                             image_size="1K")
        self.assertEqual(out, b"hi")
        self.assertEqual(calls["chat"], 1)
        self.assertEqual(calls["api"], 1)

    def test_forced_image_backend_skips_chat(self):
        llm = _llm()
        llm.image_backend = "image"
        calls = {"chat": 0, "api": 0}
        llm._call_chat_image = lambda *a, **kw: calls.__setitem__(
            "chat", calls["chat"] + 1)
        llm._post_image_api = lambda p: (calls.__setitem__(
            "api", calls["api"] + 1) or
            {"data": [{"b64_json": "aGk="}], "usage": {"cost": 0.018}})
        out = llm.make_image("P", refs=[], aspect_ratio="9:16",
                             image_size="1K")
        self.assertEqual(out, b"hi")
        self.assertEqual(calls["chat"], 0)
        self.assertEqual(calls["api"], 1)

    def test_backend_switch_from_env(self):
        import os
        os.environ["AI_IMAGE_BACKEND"] = "image"
        try:
            self.assertEqual(_llm().image_backend, "image")
        finally:
            os.environ.pop("AI_IMAGE_BACKEND", None)


class ChatEditPayloadTests(unittest.TestCase):
    def test_edit_sampling_fields_are_top_level(self):
        llm = _llm()
        llm.image_backend = "chat"
        captured = {}

        def fake_post(payload, timeout=None):
            captured.update(payload)
            return {"choices": [{"message": {"images": [
                {"image_url": {"url": "data:image/png;base64,aGk="}}]}}]}

        llm._post_openrouter = fake_post
        self.assertEqual(llm.edit_image("data:image/png;base64,AAAA", "fix"), b"hi")
        self.assertNotIn("config", captured)
        self.assertEqual(captured["temperature"], 0.25)
        self.assertIsInstance(captured["seed"], int)

if __name__ == "__main__":
    unittest.main()


class ReasoningBudgetTests(unittest.TestCase):
    """A capped thinking budget is sent and added on top of the reply budget; no cap sends no reasoning field."""

    def payload(self, **kw):
        llm, sent = _llm(), {}

        def fake_post(payload, timeout=300):
            sent.update(payload)
            return {"choices": [{"message": {"content": "{}"}}]}

        llm._post_openrouter = fake_post
        llm.make_json("P", {"type": "object"}, max_tokens=1000, **kw)
        return sent

    def test_cap_is_sent_and_added_to_max_tokens(self):
        sent = self.payload(reasoning_tokens=300)
        self.assertEqual((sent["reasoning"], sent["max_tokens"]), ({"max_tokens": 300}, 1300))

    def test_no_cap_no_reasoning_field(self):
        sent = self.payload()
        self.assertNotIn("reasoning", sent)
        self.assertEqual(sent["max_tokens"], 1000)

    def test_plain_text_takes_the_same_cap(self):
        llm, sent = _llm(), {}

        def fake_post(payload, timeout=300):
            sent.update(payload)
            return {"choices": [{"message": {"content": "ok"}}]}

        llm._post_openrouter = fake_post
        llm.make_text("P", max_tokens=1000, reasoning_tokens=300)
        self.assertEqual((sent["reasoning"], sent["max_tokens"]), ({"max_tokens": 300}, 1300))
        sent.clear()
        llm.make_text("P", max_tokens=1000)
        self.assertEqual(("reasoning" in sent, sent["max_tokens"]), (False, 1000))
