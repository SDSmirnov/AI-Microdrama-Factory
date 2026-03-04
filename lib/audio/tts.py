"""
lib/audio/tts.py — Speech and SFX generation.

Speech: via BaseLLM.make_speech (default: GeminiLLM with Gemini TTS)
SFX:    ElevenLabs  (ELEVEN_API_KEY)
"""

import os
from pathlib import Path

from lib.llm.gemini import GeminiLLM

try:
    from elevenlabs import save as eleven_save
    from elevenlabs.client import ElevenLabs
    HAS_ELEVEN = True
except ImportError:
    HAS_ELEVEN = False

# Voice name → Gemini built-in voice
VOICE_MAP: dict[str, str] = {
    "narrator":       "Rasalgethi",
    "narrator_drama": "Fenrir",
    "narrator_soft":  "Vindemiatrix",
    "male_hero":      "Orus",
    "male_deep":      "Puck",
    "male_calm":      "Umbriel",
    "male_villain":   "Algenib",
    "male_old":       "Gacrux",
    "male_casual":    "Zubenelgenubi",
    "male":           "Rasalgethi",
    "female_hero":    "Zephyr",
    "female_strict":  "Kore",
    "female_soft":    "Achernar",
    "female_mature":  "Schedar",
    "female_mystic":  "Enceladus",
    "female":         "Zephyr",
    "child":          "Leda",
    "robot":          "Iapetus",
}


# Voice name → OpenAI voice (for use with OpenRouterLLM / openai/gpt-audio)
OPENROUTER_VOICE_MAP: dict[str, str] = {
    "narrator":       "onyx",
    "narrator_drama": "fable",
    "narrator_soft":  "shimmer",
    "male_hero":      "echo",
    "male_deep":      "onyx",
    "male_calm":      "alloy",
    "male_villain":   "ash",
    "male_old":       "sage",
    "male_casual":    "echo",
    "male":           "echo",
    "female_hero":    "nova",
    "female_strict":  "coral",
    "female_soft":    "shimmer",
    "female_mature":  "ballad",
    "female_mystic":  "verse",
    "female":         "nova",
    "child":          "nova",
    "robot":          "alloy",
}


def _default_llm(api_key: str | None = None):
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("IMG_AI_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return GeminiLLM(api_key=key)


def _eleven_client(api_key: str | None = None):
    if not HAS_ELEVEN:
        raise RuntimeError("elevenlabs SDK not installed")
    key = api_key or os.getenv("ELEVEN_API_KEY")
    if not key:
        raise RuntimeError("ELEVEN_API_KEY not set")
    return ElevenLabs(api_key=key)


def parse_speech_input(text: str) -> tuple[str, str, str]:
    """Parse 'Female [tone concerned]: Hello' → (voice_key, tone, speech_text)."""
    voice = "narrator"
    tone = "neutral"

    for key in VOICE_MAP:
        if text.lower().startswith(key):
            voice = key
            text = text[len(key):].strip()
            break

    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            tone_part = text[1:end].strip()
            if tone_part.lower().startswith("tone "):
                tone = tone_part[5:].strip()
            text = text[end + 1:].strip()

    if text.startswith(":"):
        text = text[1:].strip()

    return voice.lower(), tone, text


def generate_speech(
    text: str,
    voice_key: str,
    tone: str,
    output_path: Path,
    api_key: str | None = None,
    llm=None,
    voice_map: dict | None = None,
) -> bool:
    """Generate speech via BaseLLM.make_speech. Returns True on success.

    voice_map: override the default VOICE_MAP (e.g. pass OPENROUTER_VOICE_MAP
               when using OpenRouterLLM).  If None, VOICE_MAP is used.
    """
    if llm is None:
        llm = _default_llm(api_key)

    vmap = voice_map if voice_map is not None else VOICE_MAP
    voice = vmap.get(voice_key, next(iter(vmap.values())))
    return llm.make_speech(text, voice, output_path, tone=tone)


def generate_sfx(
    prompt: str,
    duration: float,
    output_path: Path,
    api_key: str | None = None,
) -> bool:
    """Generate SFX via ElevenLabs. Returns True on success."""
    try:
        client = _eleven_client(api_key)
        result = client.text_to_sound_effects.convert(
            text=prompt,
            duration_seconds=min(duration, 22.0),
        )
        eleven_save(result, str(output_path))
        return True
    except Exception as e:
        print(f"ElevenLabs SFX error: {e}")
        return False
