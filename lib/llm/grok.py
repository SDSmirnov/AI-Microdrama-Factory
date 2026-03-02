"""
Grok LLM backend — stub (not yet implemented).
"""
from lib.llm.base import BaseLLM


class GrokLLM(BaseLLM):
    """Grok backend stub — all methods raise NotImplementedError."""

    def __init__(self, api_key: str, text_model: str = "", image_model: str = "", **kwargs):
        self.api_key = api_key
        self.text_model = text_model
        self.image_model = image_model

    def make_json(self, prompt: str, schema: dict = None) -> dict:
        raise NotImplementedError("GrokLLM is not yet implemented")

    def make_image(self, prompt: str, refs: list = None,
                   aspect_ratio: str = '9:16', image_size: str = '2K') -> bytes:
        raise NotImplementedError("GrokLLM is not yet implemented")
