"""
lib/audio/tts.py — Speech and SFX generation.

Speech: Gemini TTS  (GOOGLE_API_KEY)
SFX:    ElevenLabs  (ELEVEN_API_KEY)
"""

import os
import wave
from pathlib import Path

from google import genai
from google.genai import types

try:
    from elevenlabs.client import ElevenLabs
    HAS_ELEVEN = True
except ImportError:
    HAS_ELEVEN = False

GEMINI_MODEL_TTS = "gemini-2.5-flash-preview-tts"

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


def _gemini_client(api_key: str | None = None) -> genai.Client:
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("IMG_AI_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return genai.Client(api_key=key)


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
) -> bool:
    """Generate speech via Gemini TTS. Returns True on success."""
    client = _gemini_client(api_key)
    gemini_voice = VOICE_MAP.get(voice_key, VOICE_MAP["narrator"])

    speech_config = types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=gemini_voice)
        )
    )

    prompt = (
        f"Read the following line naturally in Russian or English (detect language).\n\n"
        f"EMOTION/TONE: {tone}\n\nTEXT TO READ:\n{text}\n\n"
        f"INSTRUCTION: Apply the emotion, but do not read these instructions aloud."
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_TTS,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=speech_config,
            ),
        )
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
                    output_path.write_bytes(data)
                return True
        return False
    except Exception as e:
        print(f"Gemini TTS error: {e}")
        return False


def generate_sfx(
    prompt: str,
    duration: float,
    output_path: Path,
    api_key: str | None = None,
) -> bool:
    """Generate SFX via ElevenLabs. Returns True on success."""
    try:
        from elevenlabs import save
        client = _eleven_client(api_key)
        result = client.text_to_sound_effects.convert(
            text=prompt,
            duration_seconds=min(duration, 22.0),
        )
        save(result, str(output_path))
        return True
    except Exception as e:
        print(f"ElevenLabs SFX error: {e}")
        return False
