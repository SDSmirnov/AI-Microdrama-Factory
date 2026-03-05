"""
Shared infrastructure: RateLimiter, retry_on_errors, BaseLLM ABC.
Single definition reused everywhere — no more per-script duplication.
"""
import functools
import logging
import random
import time
from abc import ABC, abstractmethod
from threading import Lock

logger = logging.getLogger(__name__)


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
                wait_time = (1 - self.tokens) * (60.0 / self.rpm)
                self.tokens = 0
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
                        '429' in error_str or '500' in error_str or '503' in error_str or
                        'Too Many Requests' in error_str or 'Rate limit' in error_str or
                        'Internal Server Error' in error_str or 'Service Unavailable' in error_str or
                        'timed out' in error_str.lower() or 'connection' in error_str.lower()
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
                   aspect_ratio: str = '9:16', image_size: str = '2K') -> bytes:
        """Generate an image. Returns raw PNG bytes."""
        ...

    def make_video(self, prompt: str, start_image=None, refs=None, config=None) -> bytes:
        raise NotImplementedError(f"{self.__class__.__name__} does not support make_video")

    def edit_image(self, src_img, prompt: str, refs=None) -> bytes:
        raise NotImplementedError(f"{self.__class__.__name__} does not support edit_image")

    def analyze_image(self, image, prompt: str, refs=None) -> dict:
        raise NotImplementedError(f"{self.__class__.__name__} does not support analyze_image")

    def analyze_video(self, video, prompt: str, refs=None, schema: dict = None) -> dict:
        raise NotImplementedError(f"{self.__class__.__name__} does not support analyze_video")

    def make_speech(self, text: str, voice: str, output_path: "Path", tone: str = "neutral") -> bool:
        """Generate speech audio to output_path. Returns True on success."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support make_speech")
