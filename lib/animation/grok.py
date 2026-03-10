"""
GrokAnimator — video generation via xai_sdk (Grok).

Ported from grok_animator.py.
"""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests
import xai_sdk

from lib.animation.base import BaseAnimator

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "grok-imagine-video"
DEFAULT_DURATION = 6
DEFAULT_ASPECT_RATIO = os.getenv('AI_ASPECT_RATIO', '9:16')
DEFAULT_RESOLUTION = "720p"
BATCH_SIZE = 3
BATCH_SLEEP = 30


def _build_prompt(meta: dict) -> str:
    """Build the Grok video prompt from panel metadata."""
    motion_prompt = meta.get('motion_prompt', 'Animate this.')
    dialogue = meta.get('dialogue', '')
    voiceover = meta.get('voiceover', '')

    vo_speech = ''
    if voiceover:
        if dialogue:
            vo_speech = ''
        else:
            vo_speech = f'OFFSCREEN VOICEOVER: "{voiceover}"'

    return (
        f"CRITICALLY FORBIDDEN: object morphing, adding new objects, adding new actors.\nNO tears, NO sweat, NO spitting.\n"
        f"BACKGROUND SOUNDS: SFX ONLY, NO MUSIC\n\n"
        f"VIDEO INSTRUCTIONS: Filming Action Movie. Smooth transition, high temporal consistency.\n"
        f"STYLE: Hyper-realistic cinematic photography, shot on Arri Alexa Mini LF with 50mm lens.\n\n"
        f"START: {meta.get('visual_start', '')}\n\n"
        f"CAMERA: {meta.get('lights_and_camera', '')}\n\n"
        f"ANIMATION: {motion_prompt}\n\n"
        f"{'DIALOGUE:' if dialogue else ''} {dialogue}\n\n"
        f"{vo_speech}\n\n"
    )


def _load_image_as_data_url(path: Path) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


async def _generate_batch(client, tasks: list[dict]) -> list[dict]:
    """Run a batch of video generation tasks concurrently."""
    coros = [
        client.video.generate(
            prompt=task['prompt'],
            model=DEFAULT_MODEL,
            duration=DEFAULT_DURATION,
            aspect_ratio=DEFAULT_ASPECT_RATIO,
            resolution=DEFAULT_RESOLUTION,
            image_url=task['image_url'],
        )
        for task in tasks
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    return list(zip(tasks, results))


class GrokAnimator(BaseAnimator):
    """
    Video generation via xai_sdk (Grok imagine-video).

    Single-panel interface via animate(); batch interface via run_all().
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        duration: int = DEFAULT_DURATION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        batch_size: int = BATCH_SIZE,
        batch_sleep: int = BATCH_SLEEP,
    ):
        self.api_key = api_key
        self.model = model
        self.duration = duration
        self.aspect_ratio = aspect_ratio
        self.resolution = resolution
        self.batch_size = batch_size
        self.batch_sleep = batch_sleep

    def animate(
        self,
        start_path: Path,
        end_path: Optional[Path],
        meta: dict,
        index: int,
        out_dir: Path,
    ) -> Optional[Path]:
        """Animate a single panel (synchronous wrapper around async API)."""
        out_dir.mkdir(parents=True, exist_ok=True)

        clip_id = start_path.stem.replace('_start', '').replace('_static', '')
        out_path = out_dir / f"clip_{clip_id}.mp4"

        if out_path.exists() and out_path.stat().st_size > 0:
            logger.info(f"[{index:02d}] ⏭️  Skipping: {out_path.name} already exists.")
            return out_path

        task = {
            'prompt': _build_prompt(meta),
            'image_url': _load_image_as_data_url(start_path),
            'output': out_path,
        }

        async def _run():
            client = xai_sdk.AsyncClient(api_key=self.api_key)
            pairs = await _generate_batch(client, [task])
            return pairs

        pairs = asyncio.run(_run())
        for t, result in pairs:
            if isinstance(result, Exception):
                logger.error(f"[{index:02d}] ❌ {result}")
                return None
            try:
                logger.info(f"[{index:02d}] ⬇️  Downloading {result.url}")
                video_response = requests.get(result.url, timeout=120)
                t['output'].write_bytes(video_response.content)
                logger.info(f"[{index:02d}] ✅ Saved: {t['output']}")
                return t['output']
            except Exception as e:
                logger.error(f"[{index:02d}] ❌ Download failed: {e}")
                return None

    def run_all(
        self,
        metadata_path: Path,
        panels_dir: Path,
        out_dir: Path,
    ):
        """
        Batch-animate all panels from animation_metadata.json.

        Reads *_static.png panel images, batches them BATCH_SIZE at a time
        with BATCH_SLEEP seconds between batches (matching original script logic).
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        tasks = []

        for scene in sorted(metadata.get('scenes', []), key=lambda s: s['scene_id']):
            scene_id = scene['scene_id']
            for panel in sorted(scene.get('panels', []), key=lambda p: p['panel_index']):
                panel_id = panel['panel_index']
                img_name = f"{scene_id:03d}_{panel_id:02d}_static.png"
                img_path = panels_dir / img_name

                out_name = f"clip_{scene_id:02d}_{panel_id:03d}.mp4"
                out_path = out_dir / out_name

                if out_path.exists() and out_path.stat().st_size > 0:
                    logger.info(f"SKIPPED {out_name}")
                    continue

                if not img_path.exists():
                    logger.warning(f"⚠️  Image not found: {img_path}, skipping")
                    continue

                tasks.append({
                    'prompt': _build_prompt(panel),
                    'image_url': _load_image_as_data_url(img_path),
                    'output': out_path,
                })

        if not tasks:
            logger.info("No panels to animate.")
            return

        logger.info(f"🎬 Animating {len(tasks)} panel(s) in batches of {self.batch_size}...")

        async def _run_all():
            client = xai_sdk.AsyncClient(api_key=self.api_key)
            n = 0
            while n < len(tasks):
                batch = tasks[n:n + self.batch_size]
                logger.info(f"Batch {n}:{n + len(batch) - 1}")
                pairs = await _generate_batch(client, batch)
                for t, result in pairs:
                    if isinstance(result, Exception):
                        logger.error(f"❌ {t['output'].name}: {result}")
                        continue
                    try:
                        logger.info(f"⬇️  {t['output'].name}: {result.url}")
                        video_response = requests.get(result.url, timeout=120)
                        t['output'].write_bytes(video_response.content)
                        logger.info(f"✅ Saved: {t['output']}")
                    except Exception as e:
                        logger.error(f"❌ Download failed {t['output'].name}: {e}")
                n += self.batch_size
                if n < len(tasks):
                    logger.info(f"Sleeping {self.batch_sleep}s...")
                    await asyncio.sleep(self.batch_sleep)

        asyncio.run(_run_all())
        logger.info(f"\n✅ Done. Clips in {out_dir}/")
