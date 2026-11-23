"""Shared LLM factory helpers used by all command modules."""
import logging
import sys

from lib.llm.debug import LogDebugLLM
from lib.llm.gemini import GeminiLLM
from lib.llm.manual import ManualLLM
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
    elif llm_type == "manual":
        return ManualLLM(system_prompt=system_prompt)
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


def _make_vision_llm(llm_type: str, project, system_prompt: str = "", model: str = "",
                     reasoning_effort: str = ""):
    """Build a vision-capable LLM backend for QA/continuity/refinement.

    Uses the dedicated judge model (project.qa_model, env AI_QA_MODEL) when
    one is set, so the QA judge can be swapped to a cheaper vision model
    without changing every other text call (which use AI_TEXT_MODEL).
    `model` overrides it for callers with their own judge (room-view QA).
    """
    llm = _build_vision_llm(llm_type, project, system_prompt, model)
    llm.reasoning_effort = reasoning_effort
    return llm


def _build_vision_llm(llm_type: str, project, system_prompt: str, model: str):
    judge_model = model or getattr(project, "qa_model", "") or project.text_model
    if judge_model == project.text_model:
        return _make_llm(llm_type, project, system_prompt=system_prompt)
    if llm_type == "debug":
        return LogDebugLLM()
    if llm_type == "gemini":
        if not project.gemini_api_key:
            logger.error("❌ IMG_AI_API_KEY or GOOGLE_API_KEY not set")
            sys.exit(1)
        return GeminiLLM(
            api_key=project.gemini_api_key,
            text_model=judge_model,
            image_model=project.image_model,
            system_prompt=system_prompt,
        )
    elif llm_type == "manual":
        return ManualLLM(system_prompt=system_prompt)
    else:  # openrouter (default)
        if not project.openrouter_api_key:
            logger.error("❌ OPENROUTER_API_KEY not set")
            sys.exit(1)
        return OpenRouterLLM(
            api_key=project.openrouter_api_key,
            text_model=judge_model,
            image_model=project.image_model,
            system_prompt=system_prompt,
        )
