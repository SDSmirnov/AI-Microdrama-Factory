"""
Project dataclass: config, dirs, state, and runtime caches.
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from lib.core.prompts import load_prompts
from lib.core.utils import DEFAULT_OUTPUT_DIR, DEFAULT_REF_DIR

logger = logging.getLogger(__name__)


@dataclass
class Project:
    # Directories
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    ref_dir: Path = field(default_factory=lambda: DEFAULT_REF_DIR)
    panels_dir: Path = field(default_factory=lambda: Path("cinematic_render/panels"))
    refined_dir: Path = field(default_factory=lambda: Path("cinematic_render/refined"))
    image_prompts_dir: Path = field(default_factory=lambda: Path("cinematic_render/image_prompts"))

    # Models (resolved from env at runtime)
    text_model: str = field(default_factory=lambda: os.getenv('AI_TEXT_MODEL', 'gemini-2.5-pro'))
    image_model: str = field(default_factory=lambda: os.getenv('AI_IMAGE_MODEL', 'google/gemini-3-pro-image-preview'))
    gemini_model: str = field(default_factory=lambda: os.getenv('AI_GEMINI_MODEL', 'gemini-2.5-flash'))
    max_workers: int = field(default_factory=lambda: int(os.getenv('AI_CONCURRENCY', '10')))
    # Separate limit for image generation — defaults to 5 to stay within typical image API quotas.
    # Override per-backend: export AI_IMAGE_CONCURRENCY=3
    image_workers: int = field(default_factory=lambda: int(os.getenv('AI_IMAGE_CONCURRENCY', '5')))

    # API keys
    openrouter_api_key: str = field(default_factory=lambda: os.getenv('OPENROUTER_API_KEY', ''))
    gemini_api_key: str = field(default_factory=lambda: os.getenv('IMG_AI_API_KEY', '') or os.getenv('GOOGLE_API_KEY', ''))
    grok_api_key: str = field(default_factory=lambda: os.getenv('XAI_API_KEY', ''))

    # In-memory caches (populated by artist.load_character_refs())
    character_images: dict = field(default_factory=dict)  # name → png path
    character_info: dict = field(default_factory=dict)    # name → JSON metadata

    # Token stats per model
    token_stats: dict = field(default_factory=dict)

    def state_path(self) -> Path:
        return self.output_dir / "pipeline_state.json"

    def ensure_dirs(self):
        for d in [self.output_dir, self.ref_dir, self.panels_dir,
                  self.refined_dir, self.image_prompts_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def validate_env(self, llm_type: str = None) -> list[str]:
        """Return list of validation errors for the selected backend.

        When llm_type is None, validates only the default backend (openrouter).
        """
        errors = []
        effective = llm_type or 'openrouter'
        if effective == 'openrouter':
            if not self.openrouter_api_key:
                errors.append("OPENROUTER_API_KEY is not set (required for --llm openrouter)")
        elif effective == 'gemini':
            if not self.gemini_api_key:
                errors.append("IMG_AI_API_KEY / GOOGLE_API_KEY is not set (required for --llm gemini, Veo animation, TTS, dubbing)")
        elif effective == 'grok':
            if not self.grok_api_key:
                errors.append("XAI_API_KEY is not set (required for --llm grok)")
        return errors


def load_project(style: str = 'vertical_9_16_microdrama') -> tuple['Project', dict, dict]:
    """
    Create Project from env vars, load prompts, return (project, prompts, config).
    """
    project = Project()
    project.ensure_dirs()
    prompts, config = load_prompts(style=style)
    return project, prompts, config
