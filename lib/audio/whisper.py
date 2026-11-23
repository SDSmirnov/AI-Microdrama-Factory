"""faster-whisper model from AI_WHISPER_MODEL / AI_WHISPER_DEVICE / AI_WHISPER_COMPUTE."""
import os

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


def load_whisper():
    if WhisperModel is None:
        raise RuntimeError("faster-whisper not installed; run: pip install faster-whisper")
    return WhisperModel(os.getenv('AI_WHISPER_MODEL', 'medium'),
                        device=os.getenv('AI_WHISPER_DEVICE', 'cpu'),
                        compute_type=os.getenv('AI_WHISPER_COMPUTE', 'int8'))
