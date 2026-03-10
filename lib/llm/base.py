"""
Shared infrastructure: RateLimiter, retry_on_errors, BaseLLM ABC, parse_json.
Single definition reused everywhere — no more per-script duplication.
"""
import functools
import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from threading import Lock

# Optional backend-specific retryable exception types — imported defensively
# so base.py stays usable even without a particular SDK installed.
try:
    import requests.exceptions as _req_exc
    _REQUESTS_RETRYABLE = (
        _req_exc.ConnectionError,
        _req_exc.Timeout,
        _req_exc.ReadTimeout,
        _req_exc.ChunkedEncodingError,
    )
except ImportError:
    _REQUESTS_RETRYABLE = ()

try:
    from google.api_core import exceptions as _gapi_exc
    _GOOGLE_RETRYABLE = (
        _gapi_exc.ServiceUnavailable,   # 503
        _gapi_exc.InternalServerError,  # 500
        _gapi_exc.ResourceExhausted,    # 429
        _gapi_exc.DeadlineExceeded,
    )
except ImportError:
    _GOOGLE_RETRYABLE = ()

_TYPED_RETRYABLE = _REQUESTS_RETRYABLE + _GOOGLE_RETRYABLE

logger = logging.getLogger(__name__)


def parse_json(text: str) -> dict:
    """
    Extract and parse JSON from LLM response text.

    Strategies (in order):
    1. Direct parse — fastest; works when structured-output mode returns clean JSON.
    2. Markdown fence extraction — strips ```json ... ``` wrapper.
    3. Bracket extraction — finds first { or [ and last } or ] to strip preamble/postamble.
    4. Trailing-comma fix + retry steps 1–3 — handles a common LLM formatting mistake.

    Raises json.JSONDecodeError if all strategies fail.
    """
    text = text.strip()

    def _try_parse(s: str):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    def _extract_brackets(s: str):
        for open_ch, close_ch in [('{', '}'), ('[', ']')]:
            start = s.find(open_ch)
            end = s.rfind(close_ch)
            if start != -1 and end > start:
                result = _try_parse(s[start:end + 1])
                if result is not None:
                    return result
        return None

    def _try_all(s: str):
        # 1. Direct
        r = _try_parse(s)
        if r is not None:
            return r
        # 2. Markdown fence (preserve original newlines — do NOT pre-collapse whitespace)
        m = re.search(r'```(?:json)?\s*([\[{].*?[}\]])\s*```', s, re.DOTALL)
        if m:
            r = _try_parse(m.group(1))
            if r is not None:
                return r
        # 3. Bracket extraction
        return _extract_brackets(s)

    result = _try_all(text)
    if result is not None:
        return result

    # 4. Fix trailing commas and retry all strategies
    cleaned = re.sub(r',(\s*[}\]])', r'\1', text)
    if cleaned != text:
        result = _try_all(cleaned)
        if result is not None:
            return result

    logger.error("❌ parse_json: all strategies failed. Response head: %s", text[:300])
    raise json.JSONDecodeError("Cannot extract JSON from LLM response", text, 0)


class RateLimiter:
    """Thread-safe token-bucket rate limiter."""
    def __init__(self, rpm: int):
        self.rpm = rpm
        self.tokens = float(rpm)
        self.max_tokens = float(rpm)
        self.last_update = time.time()
        self.lock = Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.max_tokens, self.tokens + elapsed * (self.rpm / 60.0))
            self.last_update = now

            if self.tokens < 1:
                # Reserve a future slot by going negative so each concurrent
                # caller gets a progressively longer wait (staggered release,
                # not thundering herd).
                wait_time = (1 - self.tokens) * (60.0 / self.rpm)
                self.tokens -= 1
            else:
                wait_time = 0
                self.tokens -= 1

        if wait_time > 0:
            time.sleep(wait_time)


def retry_on_errors(max_retries=3, backoff_factor=2):
    """Retry decorator on 429/500/503 / rate limit / server errors."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    retryable = (
                        # Type-safe check for known SDK exception types
                        (_TYPED_RETRYABLE and isinstance(e, _TYPED_RETRYABLE)) or
                        # Regex fallback for HTTP status codes wrapped in generic exceptions.
                        # Word boundaries prevent matching codes inside URLs or longer numbers.
                        bool(re.search(r'\b(429|500|503)\b', error_str)) or
                        'Too Many Requests' in error_str or 'Rate limit' in error_str or
                        'Internal Server Error' in error_str or 'Service Unavailable' in error_str or
                        'timed out' in error_str.lower() or
                        'connection refused' in error_str.lower() or
                        'connection reset' in error_str.lower()
                    )
                    if retryable:
                        retries += 1
                        if retries >= max_retries:
                            logger.error(f"    ❌ Max retries reached: {e}")
                            raise
                        wait_time = backoff_factor ** retries + random.uniform(0, 1)
                        logger.warning(f"    ⚠️  Retrying in {wait_time:.1f}s... ({retries}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise
        return wrapper
    return decorator


class BaseLLM(ABC):
    """Abstract base class for all LLM backends."""

    @abstractmethod
    def make_json(self, prompt: str, schema: dict = None) -> dict:
        """Generate structured JSON from a text prompt."""
        ...

    @abstractmethod
    def make_image(self, prompt: str, refs: list = None,
                   aspect_ratio: str = '9:16', image_size: str = '2K',
                   temperature: float = None) -> bytes:
        """Generate an image. Returns raw PNG bytes."""
        ...

    def make_video(self, prompt: str, start_image=None, refs=None, config=None) -> bytes:
        raise NotImplementedError(f"{self.__class__.__name__} does not support make_video")

    def edit_image(self, src_img, prompt: str, refs=None,
                   aspect_ratio: str = None, image_size: str = None) -> bytes:
        raise NotImplementedError(f"{self.__class__.__name__} does not support edit_image")

    def analyze_image(self, image, prompt: str, refs=None, schema: dict = None) -> dict:
        raise NotImplementedError(f"{self.__class__.__name__} does not support analyze_image")

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        raise NotImplementedError(f"{self.__class__.__name__} does not support analyze_video")

    def make_speech(self, text: str, voice: str, output_path: "Path", tone: str = "neutral") -> bool:
        """Generate speech audio to output_path. Returns True on success."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support make_speech")
