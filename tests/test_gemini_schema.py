"""Unit tests for the Gemini schema sanitizer (transport boundary).

Gemini's REST proto rejects OpenAPI-only fields such as 'additionalProperties'
in response_schema. The gemini backend sanitizes its schema once, where the
schema enters the transport; everything else passes through untouched.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm.gemini import sanitize_schema_for_gemini


class SanitizeSchemaTests(unittest.TestCase):
    def test_drops_additional_properties_at_every_level(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string", "additionalProperties": False},
                "b": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"c": {"type": "number"}},
                    "additionalProperties": False,
                }},
            },
            "additionalProperties": False,
        }
        out = sanitize_schema_for_gemini(schema)
        self.assertNotIn("additionalProperties", out)
        self.assertNotIn("additionalProperties", out["properties"]["a"])
        self.assertNotIn("additionalProperties", out["properties"]["b"]["items"])

    def test_input_not_mutated(self):
        schema = {"type": "object", "additionalProperties": False}
        sanitize_schema_for_gemini(schema)
        self.assertEqual(schema, {"type": "object", "additionalProperties": False})

    def test_everything_else_passes_through(self):
        schema = {
            "type": "object", "required": ["a"],
            "properties": {"a": {"type": "string",
                                 "enum": ["x"], "description": "d",
                                 "items": {"type": "integer"}}},
        }
        self.assertEqual(sanitize_schema_for_gemini(schema), schema)

    def test_none_passes_through(self):
        self.assertIsNone(sanitize_schema_for_gemini(None))



class TransportConfigTests(unittest.TestCase):
    def _llm(self):
        from lib.llm.gemini import GeminiLLM
        llm = GeminiLLM.__new__(GeminiLLM)
        llm.text_model, llm.image_model = "t", "i"
        llm.limiter = type("L", (), {"acquire": lambda self: None})()
        from lib.llm.seeds import SeedCounter
        llm.seeds = SeedCounter()
        self.configs = []

        def generate_content(model, contents, config):
            self.configs.append(config)
            raise RuntimeError("stop")  # config captured; no response needed

        llm.client = type("C", (), {})()
        llm.client.models = type("M", (), {"generate_content": staticmethod(generate_content)})()
        return llm

    def test_analyze_image_sanitizes_schema(self):
        llm = self._llm()
        with self.assertRaises(RuntimeError):
            llm.analyze_image("img", "p", schema={"type": "object", "additionalProperties": False})
        self.assertNotIn("additionalProperties", self.configs[0]["response_schema"])

    def test_make_image_keeps_zero_temperature(self):
        llm = self._llm()
        with self.assertRaises(RuntimeError):
            llm.make_image("p", temperature=0.0)
        self.assertEqual(self.configs[0]["temperature"], 0.0)

if __name__ == "__main__":
    unittest.main()
