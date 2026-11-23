"""
OpenRouter LLM backend — text, image, and video generation.

Text:  POST https://openrouter.ai/api/v1/chat/completions (JSON mode)
Image: POST https://openrouter.ai/api/v1/chat/completions (modalities: image+text)
Video: POST https://openrouter.ai/api/v1/videos (async: submit -> poll -> download)
"""
import base64
import json
import logging
import mimetypes
import os
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from lib.llm.base import BaseLLM, RateLimiter, parse_json, retry_on_errors
from lib.llm.routing import build_routing
from lib.llm.seeds import SeedCounter

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _raise_with_body(resp) -> None:
    """raise_for_status, keeping OpenRouter's error message (403 spend limit vs blocked request)."""
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise requests.HTTPError(f"{e} — {resp.text[:300]}", response=resp) from e
OPENROUTER_VIDEOS_URL = "https://openrouter.ai/api/v1/videos"

# The animator is selectable: Grok 1.5 (default), Grok 1.5 Lite
# ($0.02/s at 480p but FIRST-FRAME ONLY - it rejects input_references with
# a 400, measured 2026-11-12), the older x-ai/grok-imagine-video, or
# Seedance 2.0 (the only one of the set that accepts last_frame).
# lib/animation/capabilities.py holds each model's real envelope.
def _default_video_model() -> str:
    """The video model to use when the caller does not name one.

    Read at CALL time (not import time) so setting AI_VIDEO_MODEL after
    this module is imported still takes effect.
    """
    return os.getenv('AI_VIDEO_MODEL', 'x-ai/grok-imagine-video-1.5')


# The default video model. Read at CALL time via _default_video_model();
# this name stays for the callers that import it.
DEFAULT_VIDEO_MODEL = _default_video_model()
VIDEO_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "expired")

# grok-imagine-video-1.5 caps resolution at 720p and input_references at 14
# (openrouter.ai model page). 720p is the DEFAULT_VIDEO_MODEL cap — callers get
# a clamp + log instead of a 400 from the API.
VIDEO_MAX_RESOLUTION = 720
VIDEO_MAX_REFS = 14


def _clamp_resolution(resolution: str) -> str:
    """Clamp 'NNNp' resolutions above the model cap (e.g. 1080p -> 720p)."""
    raw = (resolution or "").strip().lower()
    if raw.endswith("p") and raw[:-1].isdigit():
        if int(raw[:-1]) > VIDEO_MAX_RESOLUTION:
            logger.warning(
                "Resolution %s exceeds model cap %dp — clamped to %dp.",
                resolution, VIDEO_MAX_RESOLUTION, VIDEO_MAX_RESOLUTION,
            )
            return f"{VIDEO_MAX_RESOLUTION}p"
    return resolution


class VideoPayloadError(ValueError):
    """Invalid video generation parameters (rejected before any API call)."""


def build_video_payload(
    prompt: str,
    start_image,
    duration: int = 6,
    resolution: str = "720p",
    model: str = None,
    generate_audio: bool = None,
    seed: int = None,
    aspect_ratio: str = None,
    last_frame=None,
    reference_images=None,
) -> dict:
    """Assemble the OpenRouter /api/v1/videos request body (pure, no I/O).

    Transport never builds <IMAGE_N> tags — the prompt builder owns tag order
    and must consume the same ordered `reference_images` list so <IMAGE_N>
    binds the caller's Nth reference by construction.

    Probe constraints (GROK-VIDEO-PLAN, 2026-11-10, x-ai/grok-imagine-video-1.5
    via OpenRouter):
    - reference_images given -> refs-only mode: EVERYTHING goes into
      input_references (start_image first, binding <IMAGE_0>), and no
      frame_images key is sent (the integration 400s the combination);
      last_frame has nowhere to go and is dropped.
    - no reference_images -> image-to-video mode: frame_images first_frame.

    start_image / last_frame / reference_images items: bytes, file path,
    Path, PIL.Image, data-url, or a ready content-part dict.

    Raises VideoPayloadError when total images exceed the model cap.
    """
    references = [OpenRouterLLM._to_image_part(ref) for ref in (reference_images or [])]
    if references:
        total = 1 + len(references)
        if total > VIDEO_MAX_REFS:
            raise VideoPayloadError(
                f"total image count {total} (start frame + refs) exceeds model "
                f"cap {VIDEO_MAX_REFS}."
            )
        payload: dict[str, Any] = {
            "model": model or _default_video_model(),
            "prompt": prompt,
            "duration": duration,
            "resolution": _clamp_resolution(resolution),
            "input_references": [
                OpenRouterLLM._to_image_part(start_image), *references
            ],
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if generate_audio is not None:
            payload["generate_audio"] = generate_audio
        if seed is not None:
            payload["seed"] = seed
        return payload

    frame_images = [{
        **OpenRouterLLM._to_image_part(start_image),
        "frame_type": "first_frame",
    }]
    if last_frame is not None:
        frame_images.append({
            **OpenRouterLLM._to_image_part(last_frame),
            "frame_type": "last_frame",
        })

    payload = {
        "model": model or _default_video_model(),
        "prompt": prompt,
        "duration": duration,
        "resolution": _clamp_resolution(resolution),
        "frame_images": frame_images,
    }
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if generate_audio is not None:
        payload["generate_audio"] = generate_audio
    if seed is not None:
        payload["seed"] = seed
    return payload


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
        tts_model: str = "openai/gpt-audio",
        video_model: str = None,
        text_rpm: int = 20,
        image_rpm: int = 10,
        video_rpm: int = 5,
        system_prompt: str = "",
    ):
        self.api_key = api_key
        self.text_model = text_model
        self.image_model = image_model
        self.tts_model = tts_model
        self.video_model = video_model or _default_video_model()
        self.system_prompt = system_prompt
        self.text_limiter = RateLimiter(text_rpm)
        self.image_limiter = RateLimiter(image_rpm)
        self.video_limiter = RateLimiter(video_rpm)
        # Image backend: "auto" (chat first, Image API fallback for
        # Image-API-only models), "chat" or "image" (forced).
        self.image_backend = (os.getenv("AI_IMAGE_BACKEND", "auto") or
                              "auto").strip().lower()
        if self.image_backend not in ("auto", "chat", "image"):
            self.image_backend = "auto"
        # Provider routing (see lib/llm/routing.py). OpenRouter's default
        # routing balances price against throughput/latency and lands on the
        # STANDARD service tier for Google models, where flex (the half-price
        # tier) costs the same but is not eligible by default. AI_ROUTING
        # opts into an explicit sort; AI_ROUTING_MODEL_SUFFIX additionally
        # pins the model-slug routing variant (":floor" = price sort + flex
        # eligible).
        self.routing = build_routing(
            sort=(os.getenv("AI_ROUTING_SORT", "") or "").strip().lower(),
            order=(os.getenv("AI_ROUTING_ORDER", "") or "").strip(),
            model_suffix=(os.getenv("AI_ROUTING_MODEL_SUFFIX", "") or "").strip().lower(),
        )
        # Every image render gets a DIFFERENT seed: the provider treats
        # `seed` as a hint, not a determinism guarantee (measured 2026-11-12:
        # two identical requests with seed 21 returned two different
        # images). Without this, "regenerate" can return a near-duplicate
        # of the panel it is replacing. The seed does not affect price.
        self.seeds = SeedCounter()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Connection": "close",
        }

    def _model_name(self, name: str, suffix: bool = True) -> str:
        """Resolve a model id to its OpenRouter slug.

        `suffix` controls whether the routing model-slug variant (":floor")
        is appended. It is applied to the TEXT path ONLY: the flex service
        tier exists for text models, and appending the variant to an image
        or video model id breaks the request
        (measured 2026-11-12: "google/gemini-nano-banana-2.1:floor" -> 404
        "No model found" on the Image API; the video model accepts it but
        pays no flex price).
        """
        model = _openrouter_model(name)
        if suffix and self.routing.get("model_suffix") and ":" not in model:
            model = f"{model}:{self.routing['model_suffix']}"
        return model

    def _post_openrouter(self, payload: dict, timeout: int = 300) -> dict:
        provider = self.routing.get("provider")
        if provider:
            payload = {**payload, "provider": provider}
        resp = requests.post(OPENROUTER_URL, json=payload, headers=self._headers(),
                             timeout=timeout)
        _raise_with_body(resp)
        return resp.json()

    @staticmethod
    def _extract_text(data: dict) -> str:
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content")
        if not content:  # say why: a reasoning model that spent max_tokens thinking ends with "length"
            logger.warning(f"    ⚠️  Empty reply from {data.get('model', '?')}: finish_reason="
                           f"{choice.get('finish_reason')!r} native={choice.get('native_finish_reason')!r} "
                           f"usage={data.get('usage')}")
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

    @staticmethod
    def _to_image_part(item) -> dict:
        if isinstance(item, dict):
            return item
        if isinstance(item, str) and item.startswith("data:image/"):
            return {"type": "image_url", "image_url": {"url": item}}
        data, mime = OpenRouterLLM._coerce_bytes(item, "image/png")
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

    def _call_openrouter(self, messages: list, schema: dict = None, max_tokens: int = 100000,
                         reasoning_tokens: int = 0) -> str:
        """POST to OpenRouter chat completions. Returns raw response text.
        reasoning_tokens > 0 caps the model's thinking and is added on top of max_tokens, so a reasoning
        model cannot spend the reply budget on thought (`reasoning.effort` alone is ignored by some)."""
        payload: dict[str, Any] = {
            "model": self._model_name(self.text_model),
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": max_tokens + reasoning_tokens,
        }
        if reasoning_tokens:
            payload["reasoning"] = {"max_tokens": reasoning_tokens}
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

    def make_json(self, prompt: str, schema: dict = None, max_tokens: int = 100000,
                  reasoning_tokens: int = 0) -> dict:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.text_limiter.acquire()
            content = self._call_openrouter(messages, schema, max_tokens=max_tokens,
                                            reasoning_tokens=reasoning_tokens)
            logger.debug(content)
            try:
                return parse_json(content)
            except json.JSONDecodeError as e:
                logger.error(f"    ❌ JSON parse error: {e}. Response: {content[:500]}")
                raise

        return _call()

    def make_text(self, prompt: str, system_prompt: str = None, max_tokens: int = 100000,
                  reasoning_tokens: int = 0) -> str:
        """reasoning_tokens > 0 caps the thinking on top of max_tokens, as in _call_openrouter."""
        sys = self.system_prompt if system_prompt is None else system_prompt
        messages = []
        if sys:
            messages.append({"role": "system", "content": sys})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self._model_name(self.text_model),
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens + reasoning_tokens,
        }
        if reasoning_tokens:
            payload["reasoning"] = {"max_tokens": reasoning_tokens}

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.text_limiter.acquire()
            data = self._post_openrouter(payload, timeout=300)
            return self._extract_text(data)

        return _call()

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    # --- OpenRouter Image API (POST /api/v1/images) --------------------
    # Several image models (bytedance-seed/seedream-5-0-flash,
    # minimax/minimax-h3-image, ...) are served ONLY here — the chat
    # endpoint 404s for them. Chat-first with fallback keeps every model
    # usable through one interface.

    IMAGE_API_URL = "https://openrouter.ai/api/v1/images"

    def _post_image_api(self, payload: dict) -> dict:
        resp = requests.post(self.IMAGE_API_URL, json=payload,
                             headers=self._headers(), timeout=300)
        _raise_with_body(resp)
        return resp.json()

    def _refs_to_image_api(self, refs: list) -> tuple:
        """(input_references, text_blocks) from OpenAI-style content parts."""
        images, texts = [], []
        for item in (refs or []):
            part = self._normalize_multimodal_part(item, media="image")
            if part.get("type") == "image_url":
                images.append({"type": "image_url",
                               "image_url": {"url": part["image_url"]["url"]}})
            elif part.get("type") == "text":
                texts.append(part.get("text", ""))
        return images, texts

    def _make_image_via_api(self, prompt: str, refs: list = None,
                            aspect_ratio: str = '9:16',
                            image_size: str = '2K') -> bytes:
        """Generate (or edit, when a source image leads the refs) through
        the OpenRouter Image API."""
        images, texts = self._refs_to_image_api(refs)
        full_prompt = prompt
        if texts:
            full_prompt = prompt + "\n\n" + "\n".join(texts)
        payload = {
            "model": self._model_name(self.image_model, suffix=False),
            "prompt": full_prompt,
            "resolution": image_size,
            "output_format": "png",
            "n": 1,
            # Vary the seed per call (see lib/llm/seeds.py): the provider
            # treats it as a hint, so a fixed seed would make a re-render
            # return a near-duplicate of its input.
            "seed": self.seeds.next(),
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if images:
            payload["input_references"] = images
        self.image_limiter.acquire()
        data = self._post_image_api(payload)
        try:
            item = data["data"][0]
            return base64.b64decode(item["b64_json"])
        except (KeyError, IndexError, ValueError) as parse_err:
            logger.error("Unexpected Image API response: %s", str(data)[:400])
            raise RuntimeError(f"Unexpected Image API response: {parse_err}") from parse_err

    def _call_chat_image(self, contents: list, aspect_ratio: str,
                         image_size: str, temperature: float) -> bytes:
        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.image_limiter.acquire()
            payload = {
                "model": self._model_name(self.image_model, suffix=False),
                "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": contents}],
                "image_config": {
                    "aspect_ratio": aspect_ratio,
                    "image_size": image_size,
                },
                # temperature/top_p balance creativity vs. consistency for cinematic stills.
                # The seed VARIES per call: the provider treats it as a hint,
                # not a determinism guarantee, so a fixed seed would make
                # "regenerate" return a near-duplicate of its input.
                "temperature": temperature, "seed": self.seeds.next(), "top_p": 0.8
            }
            data = self._post_openrouter(payload, timeout=180)
            try:
                image_url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
                return base64.b64decode(image_url.split(",", 1)[1])
            except (KeyError, IndexError, ValueError) as parse_err:
                logger.error("Unexpected image response: %s", data)
                raise RuntimeError(f"Unexpected image response format: {parse_err}") from parse_err

        return _call()

    def _image_via_chat_or_api(self, prompt: str, refs: list,
                               aspect_ratio: str, image_size: str,
                               temperature: float) -> bytes:
        if self.image_backend == "image":
            return self._make_image_via_api(prompt, refs, aspect_ratio,
                                             image_size)
        contents = [self._normalize_multimodal_part(item)
                    for item in (refs or [])]
        contents.append({"type": "text", "text": prompt})
        try:
            return self._call_chat_image(contents, aspect_ratio, image_size,
                                         temperature)
        except Exception as e:
            if self.image_backend != "auto":
                raise
            msg = str(e)
            # Image-API-only models 404 on chat/completions.
            if "404" not in msg and "Not Found" not in msg:
                raise
            logger.info("    image model %s is not served by chat/completions "
                        "— using the OpenRouter Image API",
                        self.image_model)
            return self._make_image_via_api(prompt, refs, aspect_ratio,
                                             image_size)

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
        _temperature = temperature if temperature is not None else 0.45
        return self._image_via_chat_or_api(prompt, refs, aspect_ratio,
                                            image_size, _temperature)

    # ------------------------------------------------------------------
    # Image editing and multimodal analysis
    # ------------------------------------------------------------------

    def edit_image(self, src_img, prompt: str, refs=None,
                   aspect_ratio: str = None, image_size: str = None) -> bytes:
        """
        Edit an existing image with optional reference context.

        Content order: character/scene refs first (visual context), source image after,
        instruction last — matches recommended multimodal ordering for appearance anchoring.

        src_img: image bytes, file path, Path, PIL.Image, data URL, or content-part dict.
        refs: optional list of context parts (text/images) prepended before source.
        aspect_ratio/image_size: accepted for API compatibility, ignored (OpenRouter handles sizing).
        Returns raw PNG bytes.
        """
        contents = []
        for ref in refs or []:
            contents.append(self._normalize_multimodal_part(ref, media="image"))
        contents.append(self._to_image_part(src_img))
        contents.append({"type": "text", "text": f"Edit the last image above. {prompt}"})

        if self.image_backend == "image":
            return self._make_image_via_api(
                prompt, refs=[self._to_image_part(src_img)] + list(refs or []),
                aspect_ratio=aspect_ratio, image_size=image_size or '2K')

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _call():
            self.image_limiter.acquire()
            payload = {
                "model": self._model_name(self.image_model, suffix=False),
                "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": contents}],
                # Vary the seed per edit for the same reason as the render
                # path: a retry must be a new sample, not a near-duplicate.
                "temperature": 0.25, "seed": self.seeds.next(), "top_p": 0.8,
            }
            data = self._post_openrouter(payload, timeout=180)
            try:
                image_url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
                return base64.b64decode(image_url.split(",", 1)[1])
            except (KeyError, IndexError, ValueError) as parse_err:
                raise RuntimeError(f"Unexpected edit-image response format: {parse_err}") from parse_err

        try:
            return _call()
        except Exception as e:
            if self.image_backend != "auto":
                raise
            msg = str(e)
            if "404" not in msg and "Not Found" not in msg:
                raise
            logger.info("    image model %s is not served by chat/completions "
                        "-- using the OpenRouter Image API", self.image_model)
            return self._make_image_via_api(
                prompt, refs=[self._to_image_part(src_img)] + list(refs or []),
                aspect_ratio=aspect_ratio, image_size=image_size or '2K')

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
            if getattr(self, 'reasoning_effort', ''):
                payload["reasoning"] = {"effort": self.reasoning_effort}
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
                return parse_json(text)
            try:
                return parse_json(text)
            except json.JSONDecodeError:
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
            "messages": [
                 {
                     "role": "system",
                     "content": (
                         "You are a voice assistant. Speak in Russian at a natural, "
                         "quick conversational pace (~150 words per minute). "
                         "Do NOT pause between sentences. Read fluently and continuously, "
                         "as if reading a news broadcast. Minimize silence gaps."
                    )
                },
                {"role": "user", "content": prompt}],
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
                return parse_json(text)
            try:
                return parse_json(text)
            except json.JSONDecodeError:
                return {"text": text}

        return _call()

    # ------------------------------------------------------------------
    # Video generation (async: submit -> poll -> download)
    # ------------------------------------------------------------------

    def generate_video(
        self,
        prompt: str,
        start_image,
        duration: int = 6,
        resolution: str = "720p",
        model: str = None,
        generate_audio: bool = None,
        seed: int = None,
        aspect_ratio: str = None,
        poll_interval: int = 10,
        timeout: int = 900,
        last_frame=None,
        reference_images=None,
    ) -> bytes:
        """
        Generate a video via OpenRouter's async video API (default: x-ai/grok-imagine-video-1.5).

        start_image: image bytes/path/Path/PIL.Image/data-url used as the animated first frame.
        last_frame: optional end-frame pin (frame_type "last_frame"). Send only
            after the OpenRouter passthrough probe confirms it (GROK-VIDEO-PLAN Item 4).
        reference_images: ordered ref list, mapped 1:1 to input_references; the
            prompt's <IMAGE_N> tags must follow this same order (Item 2 assembler).
        duration: seconds (model-dependent, 1-15 for grok-imagine-video-1.5).
        resolution: e.g. "480p", "720p" (values above the model's 720p cap are clamped).
        Returns raw video bytes (MP4). Raises TimeoutError/RuntimeError on failure.
        """
        payload = build_video_payload(
            prompt, start_image, duration=duration, resolution=resolution,
            model=model or self.video_model, generate_audio=generate_audio,
            seed=seed, aspect_ratio=aspect_ratio,
            last_frame=last_frame, reference_images=reference_images,
        )

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def _submit():
            self.video_limiter.acquire()
            body = payload
            provider = self.routing.get("provider")
            if provider:
                body = {**payload, "provider": provider}
            resp = requests.post(OPENROUTER_VIDEOS_URL, json=body, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            return resp.json()

        job = _submit()
        polling_url = job["polling_url"]
        logger.info(f"🎬 Video job {job['id']} submitted ({payload['model']}), polling {polling_url}")

        deadline = time.monotonic() + timeout
        status = job
        while status["status"] not in VIDEO_TERMINAL_STATUSES:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Video generation timed out after {timeout}s (job {job['id']})")
            time.sleep(poll_interval)
            resp = requests.get(polling_url, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            status = resp.json()
            logger.info(f"🎬 Video job {job['id']}: {status['status']}")

        if status["status"] != "completed":
            raise RuntimeError(f"Video generation {status['status']}: {status.get('error', 'unknown error')}")

        content_url = status["unsigned_urls"][0]
        video_resp = requests.get(content_url, headers=self._headers(), timeout=120)
        video_resp.raise_for_status()
        return video_resp.content
