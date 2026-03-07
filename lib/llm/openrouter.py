"""
OpenRouter LLM backend — text and image generation.

Text:  POST https://openrouter.ai/api/v1/chat/completions (JSON mode)
Image: POST https://openrouter.ai/api/v1/chat/completions (modalities: image+text)
"""
import base64
import json
import logging
import mimetypes
import os
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from lib.llm.base import BaseLLM, RateLimiter, retry_on_errors

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _openrouter_model(name: str) -> str:
    """Auto-prefix model name with 'google/' if no provider prefix is present."""
    if '/' not in name:
        return f"google/{name}"
    return name


class OpenRouterLLM(BaseLLM):
    """Text and image generation via OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        text_model: str,
        image_model: str,
        tts_model: str = "openai/gpt-4o-audio-preview",
        text_rpm: int = 20,
        image_rpm: int = 10,
        system_prompt: str = "",
    ):
        self.api_key = api_key
        self.text_model = text_model
        self.image_model = image_model
        self.tts_model = tts_model
        self.system_prompt = system_prompt
        self.text_limiter = RateLimiter(text_rpm)
        self.image_limiter = RateLimiter(image_rpm)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _model_name(self, name: str) -> str:
        return _openrouter_model(name)

    def _post_openrouter(self, payload: dict, timeout: int = 300) -> dict:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=self._headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_text(data: dict) -> str:
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        parts.append(text)
            return "\n".join(parts)
        return str(content or "")

    @staticmethod
    def _coerce_bytes(item, default_mime: str) -> tuple[bytes, str]:
        if isinstance(item, bytes):
            return item, default_mime
        if isinstance(item, str):
            p = Path(item)
            data = p.read_bytes()
            mime = mimetypes.guess_type(str(p))[0] or default_mime
            return data, mime
        if isinstance(item, Path):
            data = item.read_bytes()
            mime = mimetypes.guess_type(str(item))[0] or default_mime
            return data, mime
        if hasattr(item, "save"):  # PIL.Image-like object
            with BytesIO() as buf:
                item.save(buf, format="PNG")
                return buf.getvalue(), "image/png"
        raise TypeError(f"Unsupported media type: {type(item)!r}")

    def _to_image_part(self, item) -> dict:
        if isinstance(item, dict):
            return item
        if isinstance(item, str) and item.startswith("data:image/"):
            return {"type": "image_url", "image_url": {"url": item}}
        data, mime = self._coerce_bytes(item, "image/png")
        b64 = base64.b64encode(data).decode("utf-8")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

    def _to_video_part(self, item) -> dict:
        if isinstance(item, dict):
            return item
        if isinstance(item, str) and item.startswith("data:video/"):
            return {"type": "input_video", "video_url": {"url": item}}
        data, mime = self._coerce_bytes(item, "video/mp4")
        b64 = base64.b64encode(data).decode("utf-8")
        return {"type": "input_video", "video_url": {"url": f"data:{mime};base64,{b64}"}}

    def _normalize_multimodal_part(self, item, media: str = "image") -> dict:
        if isinstance(item, dict):
            return item
        if isinstance(item, str):
            try:
                # Only probe filesystem for short, single-line strings (likely paths, not prompts)
                if len(item) < 4096 and '\n' not in item:
                    p = Path(item)
                    if p.exists():
                        return self._to_image_part(p) if media == "image" else self._to_video_part(p)
            except OSError:
                pass
            return {"type": "text", "text": item}
        return self._to_image_part(item) if media == "image" else self._to_video_part(item)

    # ------------------------------------------------------------------
    # Text / JSON generation
    # ------------------------------------------------------------------

    def _call_openrouter(self, messages: list, schema: dict = None, max_tokens: int = 64000) -> str:
        """POST to OpenRouter chat completions. Returns raw response text."""
        payload: dict[str, Any] = {
            "model": self._model_name(self.text_model),
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": max_tokens,
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": schema,
                    "strict": False,
                }
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        data = self._post_openrouter(payload, timeout=300)
        return self._extract_text(data)

    def make_json(self, prompt: str, schema: dict = None, max_tokens: int = 64000) -> dict:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.text_limiter.acquire()
            content = self._call_openrouter(messages, schema, max_tokens=max_tokens)
            logger.debug(content)
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"    ❌ JSON parse error: {e}. Response: {content[:500]}")
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
        Generate an image via OpenRouter.

        refs: list of OpenAI-style content parts:
          {"type": "text", "text": "..."}
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}

        Returns raw PNG bytes.
        """
        contents = [self._normalize_multimodal_part(item) for item in (refs or [])]
        contents.append({"type": "text", "text": prompt})
        _temperature = temperature if temperature is not None else 0.35

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.image_limiter.acquire()
            payload = {
                "model": self._model_name(self.image_model),
                "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": contents}],
                "image_config": {
                    "aspect_ratio": aspect_ratio,
                    "image_size": image_size,
                },
                # temperature/top_p balance creativity vs. consistency for cinematic stills;
                # seed from AI_SEED env var for reproducibility across retries.
                "temperature": _temperature, "seed": int(os.getenv('AI_SEED', '21')), "top_p": 0.8
            }
            data = self._post_openrouter(payload, timeout=180)
            try:
                image_url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
                return base64.b64decode(image_url.split(",", 1)[1])
            except (KeyError, IndexError, ValueError) as parse_err:
                logger.debug("Unexpected image response: %s", data)
                raise RuntimeError(f"Unexpected image response format: {parse_err}") from parse_err

        return _call()

    # ------------------------------------------------------------------
    # Image editing and multimodal analysis
    # ------------------------------------------------------------------

    def edit_image(self, src_img, prompt: str, refs=None) -> bytes:
        """
        Edit an existing image with optional reference context.

        src_img: image bytes, file path, Path, PIL.Image, data URL, or content-part dict.
        refs: optional list of extra context parts (text/images).
        Returns raw PNG bytes.
        """
        contents = [self._to_image_part(src_img)]
        for ref in refs or []:
            contents.append(self._normalize_multimodal_part(ref, media="image"))
        contents.append({"type": "text", "text": f"Edit the first image. {prompt}"})

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.image_limiter.acquire()
            payload = {
                "model": self._model_name(self.image_model),
                "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": contents}],
                "config": {"temperature": 0.25, "seed": 42, "top_p": 0.8},
            }
            data = self._post_openrouter(payload, timeout=180)
            try:
                image_url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
                return base64.b64decode(image_url.split(",", 1)[1])
            except (KeyError, IndexError, ValueError) as parse_err:
                raise RuntimeError(f"Unexpected edit-image response format: {parse_err}") from parse_err

        return _call()

    def analyze_image(self, image, prompt: str, refs=None, schema: dict = None) -> dict:
        """
        Analyze one or more images with optional references and prompt instructions.

        image: single image item or list of multimodal items.
        refs: optional list prepended before image(s).
        schema: optional JSON schema for structured output.
        """
        contents: list[dict] = []
        for ref in refs or []:
            contents.append(self._normalize_multimodal_part(ref, media="image"))

        if isinstance(image, list):
            for item in image:
                contents.append(self._normalize_multimodal_part(item, media="image"))
        else:
            contents.append(self._normalize_multimodal_part(image, media="image"))

        if prompt:
            contents.append({"type": "text", "text": prompt})

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.text_limiter.acquire()
            payload: dict[str, Any] = {
                "model": self._model_name(self.text_model),
                "messages": [{"role": "user", "content": contents}],
                "temperature": 0.2,
                "max_tokens": 32000,
            }
            if schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "image_analysis",
                        "schema": schema,
                        "strict": False,
                    },
                }
            data = self._post_openrouter(payload, timeout=180)
            text = self._extract_text(data)
            if schema:
                return json.loads(text)
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}

        return _call()

    # ------------------------------------------------------------------
    # TTS via openai/gpt-audio (SSE streaming)
    # ------------------------------------------------------------------

    # Voices supported by openai/gpt-audio
    _OPENAI_VOICES = frozenset({
        "alloy", "ash", "ballad", "coral", "echo",
        "fable", "onyx", "nova", "sage", "shimmer", "verse",
    })

    def make_speech(self, text: str, voice: str, output_path: "Path", tone: str = "neutral") -> bool:
        """
        Generate TTS via OpenRouter (openai/gpt-audio) and write audio to output_path.

        text:  plain text to synthesize (gpt-audio reads it literally; tone is ignored).
        voice: OpenAI voice name (alloy, ash, ballad, coral, echo, fable,
               onyx, nova, sage, shimmer, verse). Falls back to "alloy" if unknown.
        Returns True on success.
        """
        if voice not in self._OPENAI_VOICES:
            voice = "alloy"

        tone_clause = f" with a {tone} tone" if tone and tone != "neutral" else ""
        prompt = (
            f"Read the following text aloud exactly as written{tone_clause}, "
            f"without adding any commentary:\n\n{text}"
        )

        # OpenRouter requires stream=True for audio; streaming requires pcm16 format.
        payload = {
            "model": self.tts_model,
            "modalities": ["text", "audio"],
            "audio": {"voice": voice, "format": "pcm16"},
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }

        try:
            resp = requests.post(
                OPENROUTER_URL,
                json=payload,
                headers=self._headers(),
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            audio_chunks: list[str] = []
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line if isinstance(raw_line, bytes) else raw_line.encode()
                if not line.startswith(b"data: "):
                    continue
                data = line[6:]
                if data == b"[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    audio_b64 = (delta.get("audio") or {}).get("data")
                    if audio_b64:
                        audio_chunks.append(audio_b64)
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue

            if not audio_chunks:
                logger.error("❌ OpenRouter TTS: no audio data in response")
                return False

            pcm_bytes = base64.b64decode("".join(audio_chunks))
            out = Path(output_path)
            if out.suffix.lower() == ".wav":
                with wave.open(str(out), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(pcm_bytes)
            else:
                out.write_bytes(pcm_bytes)
            return True

        except Exception as e:
            logger.error(f"❌ OpenRouter TTS error: {e}")
            return False

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        """
        Analyze a video clip with optional references via OpenRouter multimodal chat.

        video: video bytes/path/data-url/content-part dict, or list of multimodal items.
        refs: optional list of context items (text/images/videos).
        """
        contents: list[dict] = []
        for ref in refs or []:
            if isinstance(ref, dict):
                contents.append(ref)
            elif isinstance(ref, str):
                p = Path(ref)
                if p.exists():
                    mime = mimetypes.guess_type(str(p))[0] or ""
                    media = "video" if mime.startswith("video/") else "image"
                    contents.append(self._normalize_multimodal_part(p, media=media))
                else:
                    contents.append({"type": "text", "text": ref})
            else:
                contents.append(self._normalize_multimodal_part(ref, media="image"))

        if isinstance(video, list):
            for item in video:
                if isinstance(item, dict):
                    contents.append(item)
                elif isinstance(item, str):
                    p = Path(item)
                    if p.exists():
                        mime = mimetypes.guess_type(str(p))[0] or ""
                        media = "video" if mime.startswith("video/") else "image"
                        contents.append(self._normalize_multimodal_part(p, media=media))
                    else:
                        contents.append({"type": "text", "text": item})
                else:
                    contents.append(self._to_video_part(item))
        else:
            contents.append(self._to_video_part(video))

        if prompt:
            contents.append({"type": "text", "text": prompt})

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.text_limiter.acquire()
            payload: dict[str, Any] = {
                "model": self._model_name(self.text_model),
                "messages": [{"role": "user", "content": contents}],
                "temperature": 0.2,
                "max_tokens": 32000,
            }
            if schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "video_analysis",
                        "schema": schema,
                        "strict": False,
                    },
                }
            data = self._post_openrouter(payload, timeout=240)
            text = self._extract_text(data)
            if schema:
                return json.loads(text)
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}

        return _call()
