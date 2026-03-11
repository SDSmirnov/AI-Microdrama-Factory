"""Shared LLM factory helpers used by all command modules."""
import logging
import sys

from lib.llm.debug import LogDebugLLM
from lib.llm.gemini import GeminiLLM
from lib.llm.openrouter import OpenRouterLLM

logger = logging.getLogger(__name__)


def _make_llm(llm_type: str, project, system_prompt: str = ""):
    """Build an LLM backend from --llm flag."""
    if llm_type == "gemini":
        if not project.gemini_api_key:
            logger.error("❌ IMG_AI_API_KEY or GOOGLE_API_KEY not set")
            sys.exit(1)
        return GeminiLLM(
            api_key=project.gemini_api_key,
            text_model=project.text_model,
            image_model=project.image_model,
            system_prompt=system_prompt,
        )
    elif llm_type == "debug":
        return LogDebugLLM()
    else:  # openrouter (default)
        if not project.openrouter_api_key:
            logger.error("❌ OPENROUTER_API_KEY not set")
            sys.exit(1)
        return OpenRouterLLM(
            api_key=project.openrouter_api_key,
            text_model=project.text_model,
            image_model=project.image_model,
            system_prompt=system_prompt,
        )


def _make_vision_llm(llm_type: str, project, system_prompt: str = ""):
    """Build a vision-capable LLM backend for QA/continuity/refinement."""
    return _make_llm(llm_type, project, system_prompt=system_prompt)
