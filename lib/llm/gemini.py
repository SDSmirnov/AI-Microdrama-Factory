"""
Gemini LLM backend — text, image, and video via google.genai SDK.

Used for QA (05_grid_quality_gate), continuity (06_continuity_enforcer),
panel refinement, and Veo animation.
"""
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from lib.llm.base import BaseLLM, RateLimiter

logger = logging.getLogger(__name__)

SAFETY = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


class GeminiLLM(BaseLLM):
    """Text / image / video via google.genai SDK."""

    def __init__(
        self,
        api_key: str,
        text_model: str = "gemini-2.5-flash",
        image_model: str = "gemini-3-pro-image-preview",
        video_model: str = "veo-3.1-fast-generate-preview",
        rpm: int = 30,
    ):
        self.api_key = api_key
        self.text_model = text_model
        self.image_model = image_model
        self.video_model = video_model
        self.limiter = RateLimiter(rpm)

        from google import genai
        self.client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # JSON generation
    # ------------------------------------------------------------------

    def make_json(self, prompt: str, schema: dict = None) -> dict:
        self.limiter.acquire()
        config: dict[str, Any] = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 32000,
            "safety_settings": SAFETY,
        }
        if schema:
            config["response_schema"] = schema

        try:
            resp = self.client.models.generate_content(
                model=self.text_model,
                contents=prompt,
                config=config,
            )
            return json.loads(resp.text)
        except Exception as e:
            logger.error(f"❌ Gemini JSON error: {e}")
            raise

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    def make_image(
        self,
        prompt: str,
        refs: list = None,
        aspect_ratio: str = '9:16',
        image_size: str = '1K',
    ) -> bytes:
        """
        Generate an image via Gemini.

        refs: mixed list of PIL.Image objects and str text blocks.
        Returns raw PNG bytes.
        """
        from PIL import Image as _PILImage
        from google.genai import types

        def _to_part(item):
            if isinstance(item, str):
                return types.Part.from_text(text=item)
            if isinstance(item, _PILImage.Image):
                buf = BytesIO()
                item.save(buf, format='PNG')
                return types.Part.from_bytes(data=buf.getvalue(), mime_type='image/png')
            return item

        contents = [_to_part(item) for item in (refs or [])]
        contents.append(types.Part.from_text(text=prompt))

        self.limiter.acquire()
        try:
            resp = self.client.models.generate_content(
                model=self.image_model,
                contents=contents,
                config={
                    'response_modalities': ['Image'],
                    'image_config': {
                        'aspect_ratio': aspect_ratio,
                        'image_size': image_size,
                    },
                    'safety_settings': SAFETY,
                }
            )
            if resp.parts and resp.parts[0].inline_data:
                with BytesIO() as buf:
                    resp.parts[0].as_image().save(buf, format="PNG")
                    return buf.getvalue()
            return b''
        except Exception as e:
            logger.error(f"❌ Gemini image error: {e}")
            raise

    def edit_image(self, src_img, prompt: str, refs=None) -> bytes:
        """
        Edit an existing image with optional reference images/text.

        src_img: path, Path, PIL.Image-like object, or bytes.
        refs: optional list of paths/PIL images/text blocks.
        Returns raw PNG bytes.
        """
        from PIL import Image

        def _as_content(item):
            if isinstance(item, (str, Path)):
                return Image.open(item)
            return item

        target = _as_content(src_img)
        contents = [f"Edit the first image, apply the following changes: {prompt}", target]
        for ref in refs or []:
            contents.append(_as_content(ref))

        self.limiter.acquire()
        try:
            resp = self.client.models.generate_content(
                model=self.image_model,
                contents=contents,
                config={
                    "response_modalities": ["Image"],
                    "safety_settings": SAFETY,
                },
            )
            if resp.parts and resp.parts[0].inline_data:
                with BytesIO() as buf:
                    resp.parts[0].as_image().save(buf, format="PNG")
                    return buf.getvalue()
            return b""
        except Exception as e:
            logger.error(f"❌ Gemini edit_image error: {e}")
            raise

    # ------------------------------------------------------------------
    # Image analysis (for QA gate)
    # ------------------------------------------------------------------

    def analyze_image(self, image, prompt: str, refs=None, schema: dict = None) -> dict:
        """
        Analyze image(s) via Gemini multimodal.

        image:  PIL.Image or list of content items
        refs:   optional list of content items prepended before image
        schema: optional JSON schema for structured output
        """
        from google.genai import types

        def _to_part(item):
            # Wrap raw strings as text Parts so the SDK doesn't try to open them as files
            if isinstance(item, str):
                return types.Part.from_text(text=item)
            return item  # PIL.Image and other types handled natively by the SDK

        contents: list[Any] = []
        if refs:
            contents.extend(_to_part(r) for r in refs)
        if isinstance(image, list):
            contents.extend(_to_part(item) for item in image)
        else:
            contents.append(_to_part(image))
        contents.append(types.Part.from_text(text=prompt))

        config: dict[str, Any] = {
            "safety_settings": SAFETY,
            "temperature": 0.2,
            "max_output_tokens": 32048,
        }
        if schema:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        self.limiter.acquire()
        try:
            resp = self.client.models.generate_content(
                model=self.text_model,
                contents=contents,
                config=config,
            )
            if schema:
                return json.loads(resp.text)
            return {"text": resp.text}
        except Exception as e:
            logger.error(f"❌ Gemini analyze_image error: {e}")
            return {}

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        """
        Analyze video(s) via Gemini multimodal.

        video: bytes, path/Path, content item, or list of items.
        refs: optional content items prepended before video.
        schema: optional JSON schema for structured output.
        """
        from google.genai import types

        def _as_video_part(item):
            if isinstance(item, (str, Path)):
                p = Path(item)
                if p.exists():
                    return types.Part.from_bytes(
                        data=p.read_bytes(),
                        mime_type="video/mp4",
                    )
                return item
            if isinstance(item, bytes):
                return types.Part.from_bytes(
                    data=item,
                    mime_type="video/mp4",
                )
            return item

        contents: list[Any] = []
        if refs:
            contents.extend(refs)
        if isinstance(video, list):
            for item in video:
                contents.append(_as_video_part(item))
        else:
            contents.append(_as_video_part(video))
        contents.append(prompt)

        config: dict[str, Any] = {
            "safety_settings": SAFETY,
            "temperature": 0.2,
            "max_output_tokens": 32048,
        }
        if schema:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        self.limiter.acquire()
        try:
            resp = self.client.models.generate_content(
                model=self.text_model,
                contents=contents,
                config=config,
            )
            if schema:
                return json.loads(resp.text)
            return {"text": resp.text}
        except Exception as e:
            logger.error(f"❌ Gemini analyze_video error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Video generation (Veo)
    # ------------------------------------------------------------------

    def make_video(self, prompt: str, start_image=None, refs=None, config=None) -> bytes:
        """
        Generate video via Veo (google.genai).

        start_image: dict {"image_bytes": bytes, "mime_type": "image/png"}
        config: dict or types.GenerateVideosConfig
        Returns raw MP4 bytes.
        """
        import time
        from google.api_core import exceptions as gapi_exceptions
        from google.genai import types

        veo_config = config or {
            'duration_seconds': 4,
            'aspect_ratio': "16:9",
            'resolution': '720p',
        }

        try:
            source = types.GenerateVideosSource(prompt=prompt)
            if start_image:
                if isinstance(start_image, types.Image):
                    source.image = start_image
                elif isinstance(start_image, dict):
                    source.image = types.Image(**start_image)
                else:
                    source.image = start_image

            if start_image:
                operation = self.client.models.generate_videos(
                    model=self.video_model,
                    source=source,
                    config=veo_config,
                )
            else:
                operation = self.client.models.generate_videos(
                    model=self.video_model,
                    source=source,
                    config=veo_config,
                )

            poll_interval = 10
            while not operation.done:
                time.sleep(poll_interval)
                poll_interval = min(poll_interval * 2, 60)
                operation = self.client.operations.get(operation)

            if operation.error:
                raise RuntimeError(f"Veo API error: {operation.error}")

            if not operation.response.generated_videos:
                return b''

            video = operation.response.generated_videos[0]
            return self.client.files.download(file=video)

        except gapi_exceptions.ResourceExhausted:
            logger.error("🛑 Veo quota exhausted (429). Stop and retry tomorrow.")
            raise
        except Exception as e:
            logger.error(f"❌ Veo error: {e}")
            return b''
