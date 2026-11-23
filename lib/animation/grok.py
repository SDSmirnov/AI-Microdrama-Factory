"""
GrokAnimator — video generation via xai_sdk (Grok).

Ported from grok_animator.py.
"""
import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Optional

import requests
import xai_sdk

from lib.animation.base import BaseAnimator, clip_path_for_panel
from lib.animation.capabilities import caps_for
from lib.animation.prompt_builder import build_video_prompt

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "grok-imagine-video"
DEFAULT_DURATION = 6
DEFAULT_ASPECT_RATIO = '9:16'
DEFAULT_RESOLUTION = "720p"
BATCH_SIZE = 9
BATCH_SLEEP = 30


def _load_image_as_data_url(path: Path) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


async def _generate_batch(client, tasks: list[dict], model: str, aspect_ratio: str,
                          resolution: str) -> list[dict]:
    """Run a batch of video generation tasks concurrently."""
    coros = [
        client.video.generate(
            prompt=task['prompt'],
            model=model,
            duration=task['duration'],
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            image_url=task['image_url'],
        )
        for task in tasks
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    return list(zip(tasks, results))


def _download(url: str, out: Path) -> None:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"Empty video body from {url}")
    out.write_bytes(response.content)


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
        prompts: dict = None,
    ):
        self.api_key = api_key
        self.prompts = prompts
        self.model = model
        self.duration = duration
        self.aspect_ratio = aspect_ratio
        self.resolution = resolution
        self.batch_size = batch_size
        self.batch_sleep = batch_sleep

    def _task(self, meta: dict, image: Path, out: Path) -> dict:
        seconds = caps_for(self.model).clamp_seconds(meta.get('duration') or self.duration, using_references=False)
        return {
            'prompt': build_video_prompt(meta, [], [], seconds, prompts=self.prompts),
            'duration': seconds,
            'image_url': _load_image_as_data_url(image),
            'output': out,
        }

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

        out_path = clip_path_for_panel(start_path, out_dir)

        if out_path.exists() and out_path.stat().st_size > 0:
            logger.info(f"[{index:02d}] ⏭️  Skipping: {out_path.name} already exists.")
            return out_path

        task = self._task(meta, start_path, out_path)

        async def _run():
            client = xai_sdk.AsyncClient(api_key=self.api_key)
            pairs = await _generate_batch(client, [task], self.model, self.aspect_ratio, self.resolution)
            return pairs

        pairs = asyncio.run(_run())
        for t, result in pairs:
            if isinstance(result, Exception):
                logger.error(f"[{index:02d}] ❌ {result}")
                return None
            try:
                logger.info(f"[{index:02d}] ⬇️  Downloading {result.url}")
                _download(result.url, t['output'])
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
        scene_filter: int = None,
        panel_filter: int = None,
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
            if scene_filter is not None and scene_id != scene_filter:
                continue
            for panel in sorted(scene.get('panels', []), key=lambda p: p['panel_index']):
                panel_id = panel['panel_index']
                if panel_filter is not None and panel_id != panel_filter:
                    continue
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

                tasks.append(self._task(panel, img_path, out_path))

        if not tasks:
            logger.info("No panels to animate.")
            return

        logger.info(f"🎬 Animating {len(tasks)} panel(s) in batches of {self.batch_size}...")
        failures: list[tuple[str, BaseException]] = []

        async def _run_all():
            client = xai_sdk.AsyncClient(api_key=self.api_key)
            n = 0
            while n < len(tasks):
                batch = tasks[n:n + self.batch_size]
                logger.info(f"Batch {n}:{n + len(batch) - 1}")
                pairs = await _generate_batch(client, batch, self.model, self.aspect_ratio, self.resolution)
                for t, result in pairs:
                    if isinstance(result, BaseException):
                        if not isinstance(result, Exception):
                            raise result
                        failures.append((t['output'].name, result))
                        logger.error(f"❌ {t['output'].name}: {result}")
                        continue
                    try:
                        logger.info(f"⬇️  {t['output'].name}: {result.url}")
                        await asyncio.to_thread(_download, result.url, t['output'])
                        logger.info(f"✅ Saved: {t['output']}")
                    except Exception as e:
                        failures.append((t['output'].name, e))
                        logger.error(f"❌ Download failed {t['output'].name}: {e}")
                n += self.batch_size
                if n < len(tasks):
                    logger.info(f"Sleeping {self.batch_sleep}s...")
                    await asyncio.sleep(self.batch_sleep)

        asyncio.run(_run_all())

        if failures:
            names = ", ".join(name for name, _ in failures[:5])
            more = "" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"
            raise RuntimeError(
                f"{len(failures)}/{len(tasks)} clip(s) failed: {names}{more}")

        logger.info(f"\n✅ Done. Clips in {out_dir}/")
