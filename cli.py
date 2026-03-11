#!/usr/bin/env python3
"""
cli.py — Single entry point for the video-book pipeline.

Usage:
    python cli.py init
    python cli.py styles s01e01.txt --style realistic_movie
    python cli.py casting s01e01.txt [--style vertical_9_16_microdrama]
    python cli.py screenplay s01e01.txt [--style vertical_9_16_microdrama]
    python cli.py scenes [SCENE|all] [--style vertical_9_16_microdrama]
    python cli.py reverse-refine N [--style vertical_9_16_microdrama]
    python cli.py consistency
    python cli.py storyboard [SCENE|all] [--style vertical_9_16_microdrama]
    python cli.py qa [--scene N [--panel N ...]] [--threshold N]
    python cli.py apply-qa [--scene N] [--frame start|end|static|both]
    python cli.py accept-qa
    python cli.py rebuild-storyboard [SCENE|all]
    python cli.py refinement SCENE PANEL [--frame start|end|both]
    python cli.py animation PROVIDER [SCENE|all] [PANEL|all]

    # Post-production tools
    python cli.py autocut --json scene.json --clips-dir clips/ --out-dir cut/
    python cli.py imgedit output.png "make the sky purple" source.png [ref.png ...]
    python cli.py tts speech "Female [tone sad]: Hello world" out.wav
    python cli.py tts sfx "Loud explosion" 3 expl.mp3
    python cli.py voiceover [--out-dir cinematic_render/voiceover] [--output voiceover.sh]
    python cli.py dub video.mp4 output.mp3 [context.txt]
    python cli.py duck video.mp4 dubbed.mp3 output.mp3
    python cli.py summary s01e01.txt [--output summary.txt]
    python cli.py --llm openrouter --style vertical_9_16_microdrama split-book fullbook.txt [--output-dir book-split] [--season 1]
"""
import argparse
import datetime
import logging
import os
import shlex
import sys

from lib.commands import animation, audio, screenplay, setup, storyboard

logging.basicConfig(
    level=os.getenv('AI_LOG_LEVEL', 'INFO'),
    format='%(levelname)s: %(message)s'
)


def main():
    parser = argparse.ArgumentParser(
        description="Video-book pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--llm', choices=['openrouter', 'gemini', 'debug'], default='openrouter',
        help='LLM backend for text/image generation (default: openrouter)'
    )
    parser.add_argument(
        '--style', default='vertical_9_16_microdrama',
        help='Prompting style preset from lib/prompting/ (default: vertical_9_16_microdrama)'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    for mod in [setup, screenplay, storyboard, animation, audio]:
        mod.register(sub)

    args = parser.parse_args()

    def _log_command(event: str):
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        argv = shlex.join(sys.argv[1:])
        with open('project.log', 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] [{event}] {argv}\n")

    _log_command('start')
    try:
        args.func(args)
    except FileNotFoundError as e:
        logging.error(f"❌ {e}")
        sys.exit(1)
    finally:
        _log_command('ended')


if __name__ == '__main__':
    main()
