"""
Gemini LLM backend — text, image, and video via google.genai SDK.

Used for QA (05_grid_quality_gate), continuity (06_continuity_enforcer),
panel refinement, and Veo animation.
"""
import json
import logging
import os
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

from google import genai
from google.api_core import exceptions as gapi_exceptions
from google.genai import types
from PIL import Image as PILImage

from lib.llm.base import BaseLLM, RateLimiter, parse_json, retry_on_errors

logger = logging.getLogger(__name__)

# AI_SAFETY_LEVEL=permissive (default) disables all content filters — required for
# fictional violence/adult content in creative pipelines.
# Set AI_SAFETY_LEVEL=default to use Google SDK defaults instead.
_SAFETY_PERMISSIVE = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
SAFETY = _SAFETY_PERMISSIVE if os.getenv('AI_SAFETY_LEVEL', 'permissive') == 'permissive' else []


class GeminiLLM(BaseLLM):
    """Text / image / video via google.genai SDK."""

    def __init__(
        self,
        api_key: str,
        text_model: str = "gemini-2.5-flash",
        image_model: str = "gemini-3-pro-image-preview",
        video_model: str = "veo-3.1-fast-generate-preview",
        tts_model: str = "gemini-2.5-flash-preview-tts",
        rpm: int = 30,
        system_prompt: str = "",
    ):
        self.api_key = api_key
        self.text_model = text_model
        # Strip OpenRouter-style "google/" prefix — the native Gemini SDK doesn't use it
        self.image_model = image_model.removeprefix("google/")
        self.video_model = video_model
        self.tts_model = tts_model
        self.system_prompt = system_prompt
        self.limiter = RateLimiter(rpm)

        self.client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # JSON generation
    # ------------------------------------------------------------------

    def make_json(self, prompt: str, schema: dict = None, max_tokens: int = 32000) -> dict:
        config: dict[str, Any] = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": max_tokens,
            "safety_settings": SAFETY,
        }
        if self.system_prompt:
            config["system_instruction"] = self.system_prompt
        if schema:
            config["response_schema"] = schema

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.limiter.acquire()
            try:
                resp = self.client.models.generate_content(
                    model=self.text_model,
                    contents=prompt,
                    config=config,
                )
                try:
                    return parse_json(resp.text)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Gemini JSON parse error: {e}. Response: {resp.text[:500]}")
                    raise
            except json.JSONDecodeError:
                raise
            except Exception as e:
                logger.error(f"❌ Gemini JSON error: {e}")
                raise

        return _call()

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    def make_image(
        self,
        prompt: str,
        refs: list = None,
        aspect_ratio: str = '9:16',
        image_size: str = '2K',
        temperature: float = None,
    ) -> bytes:
        """
        Generate an image via Gemini.

        refs: mixed list of PIL.Image objects and str text blocks.
        temperature: ignored (Imagen does not support temperature).
        Returns raw PNG bytes.
        """
        def _to_part(item):
            if isinstance(item, str):
                return types.Part.from_text(text=item)
            if isinstance(item, PILImage.Image):
                buf = BytesIO()
                item.save(buf, format='PNG')
                return types.Part.from_bytes(data=buf.getvalue(), mime_type='image/png')
            return item

        contents = [_to_part(item) for item in (refs or [])]
        contents.append(types.Part.from_text(text=prompt))

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
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
                raise RuntimeError("Empty image response from Gemini — no inline_data in response parts")
            except Exception as e:
                logger.error(f"❌ Gemini image error: {e}")
                raise

        return _call()

    def edit_image(self, src_img, prompt: str, refs=None,
                   aspect_ratio: str = None, image_size: str = None) -> bytes:
        """
        Edit an existing image with optional reference images/text.

        Content order: character/scene refs first (visual context), then source image,
        then instruction — this gives the model appearance anchors before it sees the
        source, matching recommended Imagen/Nano Banana multimodal ordering.

        src_img: path, Path, PIL.Image-like object, or bytes.
        refs: optional list of paths/PIL images/text blocks — prepended before source.
        aspect_ratio/image_size: optional output size override (preserves source if omitted).
        Returns raw PNG bytes.
        """
        def _as_content(item):
            if isinstance(item, Path):
                return PILImage.open(item)
            return item

        # Refs (character/scene appearance context) come first, then source image, then instruction
        contents = []
        for ref in refs or []:
            contents.append(_as_content(ref))
        contents.append(_as_content(src_img))
        contents.append(types.Part.from_text(text=f"Edit the last image above: {prompt}"))

        gen_config: dict = {"response_modalities": ["Image"], "safety_settings": SAFETY}
        img_cfg = {}
        if aspect_ratio:
            img_cfg['aspect_ratio'] = aspect_ratio
        if image_size:
            img_cfg['image_size'] = image_size
        if img_cfg:
            gen_config['image_config'] = img_cfg

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.limiter.acquire()
            try:
                resp = self.client.models.generate_content(
                    model=self.image_model,
                    contents=contents,
                    config=gen_config,
                )
                if resp.parts and resp.parts[0].inline_data:
                    with BytesIO() as buf:
                        resp.parts[0].as_image().save(buf, format="PNG")
                        return buf.getvalue()
                raise RuntimeError("Empty edit_image response from Gemini — no inline_data in response parts")
            except Exception as e:
                logger.error(f"❌ Gemini edit_image error: {e}")
                raise

        return _call()

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

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.limiter.acquire()
            try:
                resp = self.client.models.generate_content(
                    model=self.text_model,
                    contents=contents,
                    config=config,
                )
                if schema:
                    return parse_json(resp.text)
                return {"text": resp.text}
            except Exception as e:
                logger.error(f"❌ Gemini analyze_image error: {e}")
                raise

        return _call()

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        """
        Analyze video(s) via Gemini multimodal.

        video: bytes, path/Path, content item, or list of items.
        refs: optional content items prepended before video.
        schema: optional JSON schema for structured output.
        """
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
        contents.append(types.Part.from_text(text=prompt))

        config: dict[str, Any] = {
            "safety_settings": SAFETY,
            "temperature": 0.2,
            "max_output_tokens": 32048,
        }
        if schema:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.limiter.acquire()
            try:
                resp = self.client.models.generate_content(
                    model=self.text_model,
                    contents=contents,
                    config=config,
                )
                if schema:
                    return parse_json(resp.text)
                return {"text": resp.text}
            except Exception as e:
                logger.error(f"❌ Gemini analyze_video error: {e}")
                raise

        return _call()

    # ------------------------------------------------------------------
    # TTS (speech generation)
    # ------------------------------------------------------------------

    def make_speech(self, text: str, voice: str, output_path: "Path", tone: str = "neutral") -> bool:
        """
        Generate speech via Gemini TTS and write to output_path.

        text:  plain text to synthesize.
        voice: Gemini built-in voice name (e.g. "Rasalgethi", "Zephyr").
        tone:  emotion/delivery instruction passed as a prompt preamble.
        Returns True on success.
        """
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        )
        prompt = (
            f"Read the following line naturally in Russian or English (detect language).\n\n"
            f"EMOTION/TONE: {tone}\n\nTEXT TO READ:\n{text}\n\n"
            f"INSTRUCTION: Apply the emotion, but do not read these instructions aloud."
        )
        try:
            response = self.client.models.generate_content(
                model=self.tts_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=speech_config,
                ),
            )
            if not response.candidates:
                logger.warning("❌ Gemini TTS: no candidates in response (safety block?)")
                return False
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    data = part.inline_data.data
                    mime = part.inline_data.mime_type
                    if "audio/L16" in mime or "pcm" in mime:
                        with wave.open(str(output_path), "wb") as wav:
                            wav.setnchannels(1)
                            wav.setsampwidth(2)
                            wav.setframerate(24000)
                            wav.writeframes(data)
                    else:
                        Path(output_path).write_bytes(data)
                    return True
            return False
        except Exception as e:
            logger.error(f"❌ Gemini TTS error: {e}")
            return False

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
        veo_config = config or {
            'duration_seconds': 4,
            'aspect_ratio': "16:9",
            'resolution': '720p',
        }
        max_wait_seconds = 600  # 10-minute hard limit per clip

        try:
            source = types.GenerateVideosSource(prompt=prompt)
            if start_image:
                if isinstance(start_image, types.Image):
                    source.image = start_image
                elif isinstance(start_image, dict):
                    source.image = types.Image(**start_image)
                else:
                    source.image = start_image

            operation = self.client.models.generate_videos(
                model=self.video_model,
                source=source,
                config=veo_config,
            )

            deadline = time.time() + max_wait_seconds
            poll_interval = 10
            while not operation.done:
                if time.time() > deadline:
                    op_name = getattr(operation, 'name', 'unknown')
                    logger.warning(
                        f"⚠️  Veo job timed out after {max_wait_seconds}s "
                        f"(operation={op_name}). The server-side job may still be running "
                        f"and consuming quota. Cancel it via Google AI Studio or the API."
                    )
                    raise TimeoutError(f"Veo job did not complete within {max_wait_seconds}s")
                time.sleep(poll_interval)
                poll_interval = min(poll_interval * 2, 60)
                operation = self.client.operations.get(operation)

            if operation.error:
                raise RuntimeError(f"Veo API error: {operation.error}")

            if not operation.response.generated_videos:
                raise RuntimeError("Veo returned no generated videos in response")

            video = operation.response.generated_videos[0]
            data = self.client.files.download(file=video)
            if not data:
                raise RuntimeError("Veo download returned empty data")
            return data

        except gapi_exceptions.ResourceExhausted:
            logger.error("🛑 Veo quota exhausted (429). Stop and retry tomorrow.")
            raise
        except Exception as e:
            logger.error(f"❌ Veo error: {e}")
            raise
