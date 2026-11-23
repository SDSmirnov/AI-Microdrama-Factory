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


# Room and panel QA judge: fast and cheap enough to run on every attempt.
QA_JUDGE_MODEL = 'google/gemini-3.8-flash'
QA_REASONING_EFFORT = 'low'


@dataclass
class Project:
    # Directories
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    ref_dir: Path = field(default_factory=lambda: DEFAULT_REF_DIR)
    panels_dir: Path = field(default_factory=lambda: Path("cinematic_render/panels"))
    refined_dir: Path = field(default_factory=lambda: Path("cinematic_render/refined"))
    image_prompts_dir: Path = field(default_factory=lambda: Path("cinematic_render/image_prompts"))
    bible_dir: Path = field(default_factory=lambda: Path("story_bible"))  # whole-book facts (make bible)

    # Models (resolved from env at runtime)
    #
    # Defaults are pinned to models with NO announced shutdown date. The
    # 2.5-generation ids are on a cliff (Google AI Studio deprecations,
    # 2026-11-12): from 2026-12-01 gemini-2.5-pro auto-routes to
    # gemini-3.8-flash and gemini-2.5-flash auto-routes to
    # gemini-3.5-flash-lite, so a pipeline left on 2.5 ids silently changes
    # models mid-production (a FLASH model standing in for PRO, and a
    # flash-LITE standing in for a judge). Override with AI_TEXT_MODEL /
    # AI_GEMINI_MODEL / AI_QA_MODEL.
    text_model: str = field(default_factory=lambda: os.getenv('AI_TEXT_MODEL', 'google/gemini-4-hydrogen'))
    image_model: str = field(default_factory=lambda: os.getenv('AI_IMAGE_MODEL', 'google/gemini-nano-banana-2.1'))
    gemini_model: str = field(default_factory=lambda: os.getenv('AI_GEMINI_MODEL', 'google/gemini-3.8-flash'))
    # QA/continuity/refinement judge. Defaults to text_model; set AI_QA_MODEL
    # to pick a cheaper vision judge without touching every text call.
    qa_model: str = field(default_factory=lambda: os.getenv('AI_QA_MODEL', '') or os.getenv('AI_TEXT_MODEL', 'google/gemini-4-hydrogen'))
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
        return errors


def load_project(style: str = 'vertical_9_16_microdrama') -> tuple['Project', dict, dict]:
    """
    Create Project from env vars, load prompts, return (project, prompts, config).
    """
    project = Project()
    project.ensure_dirs()
    prompts, config = load_prompts(style=style)
    return project, prompts, config
