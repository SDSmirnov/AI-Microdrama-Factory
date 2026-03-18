"""Audio commands: tts, dub, voiceover, duck, dynamic-subtitles."""
import json
import logging
import re
import shlex
import stat
import sys
from pathlib import Path

from lib.audio.dubbing import run_dubbing
from lib.audio.ducking import run_ducking
from lib.audio.tts import OPENROUTER_VOICE_MAP, generate_sfx, generate_speech, parse_speech_input
from lib.commands.common import _make_llm
from lib.core.project import Project

logger = logging.getLogger(__name__)


def cmd_tts(args):
    output = Path(args.output)
    if args.tts_command == "speech":
        voice, tone, text = parse_speech_input(args.text)
        logger.info(f"Generating speech: [{voice}] [{tone}] {text[:60]}...")
        project = Project()
        llm = _make_llm(args.llm, project)
        vmap = OPENROUTER_VOICE_MAP if args.llm == "openrouter" else None
        ok = generate_speech(text, voice, tone, output, llm=llm, voice_map=vmap)
    else:  # sfx
        logger.info(f"Generating SFX: {args.prompt} ({args.duration}s)...")
        ok = generate_sfx(args.prompt, args.duration, output)

    if ok:
        logger.info(f"✅ Saved: {output}")
    else:
        logger.error("❌ Audio generation failed")
        sys.exit(1)


def cmd_dub(args):
    project = Project()
    run_dubbing(
        video_path=args.video,
        output_path=args.output,
        context_path=args.context or "",
        plan_cache=args.plan_cache,
        transcription_cache=args.transcription_cache,
        api_key=project.gemini_api_key,
    )
    logger.info(f"\n✅ Dubbing done: {args.output}")


def cmd_voiceover(args):
    project = Project()
    meta_path = project.output_dir / "animation_metadata.json"
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'screenplay' first.")
        sys.exit(1)

    metadata = json.loads(meta_path.read_text(encoding='utf-8'))
    out_dir = args.out_dir

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"mkdir -p {shlex.quote(out_dir)}",
        "",
    ]
    count = 0

    for scene in metadata.get('scenes', []):
        scene_id = scene['scene_id']
        for panel in scene.get('panels', []):
            panel_idx = panel.get('panel_index', 0)
            vo_text = (panel.get('voiceover') or '').strip()
            if not vo_text:
                continue

            slug = re.sub(r'^[A-Za-z ]+voiceover\s*:\s*', '', vo_text, flags=re.IGNORECASE)
            slug = re.sub(r'^[A-Za-z]+\s*:\s*', '', slug)
            slug = re.sub(r'\W+', '-', slug, flags=re.UNICODE).strip('-').lower()
            slug = slug[:40] or "vo"

            out_file = f"{out_dir}/scene_{scene_id:03d}_{panel_idx:02d}_{slug}.wav"
            lines.append(
                f"python cli.py --llm \"${{LLM:-openrouter}}\" tts speech {shlex.quote(vo_text)} {shlex.quote(out_file)}"
            )
            count += 1

    lines.append("")
    script_path = Path(args.output)
    script_path.write_text("\n".join(lines), encoding='utf-8')
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    logger.info(f"✅ {script_path} written: {count} voiceover(s)")


def cmd_srt(args):
    from lib.audio.dynamic_subtitles import run_transcribe_srt
    run_transcribe_srt(
        video_path=args.video,
        output_path=args.output,
        transcription_cache=args.transcription_cache,
    )
    logger.info(f"\n✅ SRT saved: {args.output}")


def cmd_dynamic_subtitles(args):
    from lib.audio.dynamic_subtitles import run_dynamic_subtitles
    run_dynamic_subtitles(
        video_path=args.input,
        srt_path=args.srt,
        output_path=args.output,
        whisper_cache=args.whisper_cache,
        ass_output=args.ass_output,
        word_srt_output=args.word_srt_output,
        use_whisper=not args.no_whisper,
        whisper_language=args.language,
        font_size=args.font_size,
        margin_v=args.margin_v,
        overlay_only=args.overlay_only,
        overlay_fps=args.overlay_fps,
    )
    logger.info("\n✅ Dynamic subtitles done: %s", args.output)


def cmd_duck(args):
    run_ducking(
        video_path=args.video,
        dubbed_path=args.dubbed,
        output_path=args.output,
        duck_db=args.duck_db,
        threshold_db=args.threshold,
        min_silence_ms=args.min_silence,
        fade_ms=args.fade,
        padding_ms=args.padding,
        do_normalize=args.normalize,
    )
    logger.info(f"\n✅ Ducking done: {args.output}")


def register(sub):
    p = sub.add_parser('tts', help='Generate speech (Gemini TTS) or SFX (ElevenLabs)')
    p.set_defaults(func=cmd_tts)
    tts_sub = p.add_subparsers(dest='tts_command', required=True)
    sp = tts_sub.add_parser('speech', help='Generate speech from text')
    sp.add_argument('text', help='Text with optional voice/tone: "Female [tone sad]: Hello"')
    sp.add_argument('output', help='Output audio file (wav/mp3)')
    sp = tts_sub.add_parser('sfx', help='Generate sound effect')
    sp.add_argument('prompt', help='Sound description')
    sp.add_argument('duration', type=float, help='Duration in seconds')
    sp.add_argument('output', help='Output audio file (mp3)')

    p = sub.add_parser('dub', help='Smart AI dubbing pipeline (Whisper → Gemini → TTS)')
    p.add_argument('video', help='Input video file (MP4)')
    p.add_argument('output', help='Output dubbed audio (MP3)')
    p.add_argument('context', nargs='?', default='', help='Optional context text file path')
    p.add_argument('--plan-cache', default='dubbing_plan.json', help='Dubbing plan cache file')
    p.add_argument('--transcription-cache', default='transcription_cache.json', help='Whisper cache file')
    p.set_defaults(func=cmd_dub)

    p = sub.add_parser('voiceover', help='Generate voiceover.sh script from animation_metadata.json')
    p.add_argument('--out-dir', default='cinematic_render/voiceover',
                   help='Output directory for generated .wav files (default: cinematic_render/voiceover)')
    p.add_argument('--output', default='voiceover.sh',
                   help='Path for the generated shell script (default: voiceover.sh)')
    p.set_defaults(func=cmd_voiceover)

    p = sub.add_parser('srt', help='Transcribe video with Whisper → SRT file for manual editing')
    p.add_argument('video', help='Input video (MP4)')
    p.add_argument('output', help='Output SRT file')
    p.add_argument('--transcription-cache', default='transcription_cache.json',
                   help='Whisper transcription cache file')
    p.set_defaults(func=cmd_srt)

    p = sub.add_parser('dynamic-subtitles', help='Burn karaoke-style dynamic subtitles onto video')
    p.add_argument('input', help='Input video (MP4)')
    p.add_argument('output', help='Output video with subtitle overlay (MP4)')
    p.add_argument('--srt', required=True, help='Input SRT subtitle file (phrase-level)')
    p.add_argument('--no-whisper', action='store_true',
                   help='Skip Whisper alignment, use even word split')
    p.add_argument('--language', default=None,
                   help='Audio language for Whisper, e.g. "en", "ru" (auto-detect if omitted)')
    p.add_argument('--font-size', type=int, default=68, help='Subtitle font size (default: 68)')
    p.add_argument('--margin-v', type=int, default=120,
                   help='Vertical margin from bottom in pixels (default: 120)')
    p.add_argument('--whisper-cache', default='dynamic_subtitles_words.json',
                   help='Whisper word timestamps cache file')
    p.add_argument('--ass-output', default=None, help='Save generated ASS file to this path')
    p.add_argument('--word-srt-output', default=None,
                   help='Save word-level SRT to this path')
    p.add_argument('--overlay-only', action='store_true',
                   help='Output transparent overlay instead of burning onto source video. '
                        'Use .mov (ProRes 4444) or .webm (VP9) as output extension.')
    p.add_argument('--overlay-fps', type=int, default=30,
                   help='FPS for transparent overlay video (default: 30)')
    p.set_defaults(func=cmd_dynamic_subtitles)

    p = sub.add_parser('duck', help='Auto-duck original audio during dubbed speech')
    p.add_argument('video', help='Input MP4 with original audio')
    p.add_argument('dubbed', help='Dubbed audio MP3')
    p.add_argument('output', help='Output MP3 with ducking applied')
    p.add_argument('--duck-db', type=float, default=-15, help='Volume reduction in dB (default: -15)')
    p.add_argument('--threshold', type=float, default=-40, help='Speech detection threshold dB (default: -40)')
    p.add_argument('--min-silence', type=int, default=300, help='Min silence gap ms (default: 300)')
    p.add_argument('--fade', type=int, default=50, help='Fade length ms (default: 50)')
    p.add_argument('--padding', type=int, default=100, help='Padding around speech ms (default: 100)')
    p.add_argument('--normalize', action='store_true', help='Normalize output volume')
    p.set_defaults(func=cmd_duck)
