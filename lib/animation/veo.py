"""
VeoAnimator — Veo video generation via google.genai SDK.

Port of 02_image_animator.py into VeoAnimator(BaseAnimator).
"""
import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

from google import genai
from google.api_core import exceptions as gapi_exceptions
from google.genai import types
from PIL import Image

from lib.animation.base import BaseAnimator

logger = logging.getLogger(__name__)

DEFAULT_RESOLUTION = '720p'
DEFAULT_MODEL = "veo-3.1-fast-generate-preview"


class VeoAnimator(BaseAnimator):
    """Video generation via Veo (google.genai)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        resolution: str = DEFAULT_RESOLUTION,
        ref_dir: Path = Path("ref_thriller"),
        gemini_text_model: str = "gemini-2.5-pro",
    ):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.resolution = resolution
        self.ref_dir = ref_dir
        self.gemini_text_model = gemini_text_model

        # Load character image refs (name → path)
        self.character_images: dict[str, str] = {}
        for f in ref_dir.glob("*.png"):
            name = f.stem.replace("_", " ").title()
            self.character_images[name] = str(f)

    def _upload_image(self, image_path: Path) -> Optional[dict]:
        if not image_path.exists():
            return None
        return {'image_bytes': image_path.read_bytes(), 'mime_type': 'image/png'}

    def _need_references(self, meta: dict, image: Image.Image) -> list[str]:
        """Ask Gemini whether character references are needed for this panel."""
        schema = {
            "type": "object",
            "properties": {
                "need_references": {"type": "string"},
                "reason": {"type": "string"},
                "refs_to_provide": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["need_references", "reason", "refs_to_provide"],
        }
        prompt = f"""
Animation with references is expensive.
Analyze scene image and visual descriptions, identify if any of character references are indeed needed here for animation.
Example: motion_prompt or visual_end may reference something not yet present in visual start frame, or person on the first frame could have face turned from the camera.
If chars are visible for quick 4 second Veo animation, then no need to pass refs.
Find only references missing on the visual start but required for visual end according to scene.
I do not need perfect animation, but I need cheap and fast.

Scene Info:
{json.dumps(meta, indent=2)}

Response format, JSON:
{{
    'need_references': "YES or SKIP",
    'reason': "Explain why",
    'refs_to_provide': 'List of the references from scene which MUST be used, max TWO most important items'
}}
"""
        try:
            resp = self.client.models.generate_content(
                model=self.gemini_text_model,
                contents=[prompt, image],
                config={'response_mime_type': "application/json", 'response_schema': schema}
            )
            logger.debug(f"RESP: {resp.text}")
            return json.loads(resp.text).get('refs_to_provide', [])
        except Exception as e:
            logger.warning(f"⚠️  Reference check failed: {e}")
            return []

    def animate(
        self,
        start_path: Path,
        end_path: Optional[Path],
        meta: dict,
        index: int,
        out_dir: Path,
    ) -> Optional[Path]:
        clip_id = start_path.stem.replace('_start', '').replace('_static', '')
        out_path = out_dir / f"clip_{clip_id}.mp4"

        if out_path.exists() and out_path.stat().st_size > 0:
            logger.info(f"[{index:02d}] ⏭️  Skipping: {out_path.name} already exists.")
            return out_path

        motion_prompt = meta.get('motion_prompt', 'Cinematic movement')
        prompt = (
            f"Cinematic shot. {meta}. "
            "Smooth transition, high temporal consistency."
            "Style: Hyper-realistic cinematic photography, shot on Arri Alexa Mini LF with 50mm lens."
        )

        logger.info(f"[{index:02d}] 🎥 Animating: {start_path.name}")
        logger.info(f"       Prompt: {motion_prompt[:50]}...")

        img_start = self._upload_image(start_path)
        if not img_start:
            logger.error(f"[{index:02d}] ❌ Missing start image.")
            return None

        img_end = None
        if end_path and end_path.exists():
            img_end = self._upload_image(end_path)

        pil_start = Image.open(start_path)
        need_chars = self._need_references(meta, pil_start)

        ref_images = []
        for name in need_chars:
            name = name.title()
            if name in self.character_images:
                try:
                    img = Image.open(self.character_images[name])
                    ref_images.append({'image': img, 'reference_type': 'asset'})
                except Exception as e:
                    logger.warning(f"Could not load ref {name}: {e}")

        config: dict = {
            'duration_seconds': 4,
            'aspect_ratio': "16:9",
            'resolution': self.resolution,
        }

        dialogue_len = len(meta.get('dialogue', '').split(' '))

        if need_chars or dialogue_len > 15:
            config['duration_seconds'] = 8
        elif dialogue_len > 10:
            config['duration_seconds'] = 6

        try:
            if ref_images:
                formatted_refs = []
                all_refs = [{'image': pil_start}] + ref_images
                for item in all_refs:
                    pil_img = item['image']
                    b = BytesIO()
                    pil_img.save(b, format="PNG")
                    formatted_refs.append(types.VideoGenerationReferenceImage(
                        image=types.Image(image_bytes=b.getvalue(), mime_type='image/png'),
                        reference_type="asset"
                    ))

                gen_config = types.GenerateVideosConfig(
                    duration_seconds=config['duration_seconds'],
                    aspect_ratio="16:9",
                    resolution=self.resolution,
                    reference_images=formatted_refs,
                )
                operation = self.client.models.generate_videos(
                    model=self.model,
                    prompt=prompt,
                    config=gen_config,
                )
            elif img_end:
                end_cfg = dict(config)
                end_cfg['duration_seconds'] = 8
                end_cfg['last_frame'] = img_end
                operation = self.client.models.generate_videos(
                    model=self.model,
                    prompt=prompt,
                    image=img_start,
                    config=end_cfg,
                )
            else:
                operation = self.client.models.generate_videos(
                    model=self.model,
                    prompt=prompt,
                    image=img_start,
                    config=config,
                )

            while not operation.done:
                logger.info(f"[{index:02d}] ... generating")
                time.sleep(10)
                operation = self.client.operations.get(operation)

            if operation.error:
                raise RuntimeError(f"API Error: {operation.error}")

            if not operation.response.generated_videos:
                logger.warning(f"[{index:02d}] ⚠️ No video returned.")
                return None

            video = operation.response.generated_videos[0]
            video_bytes = self.client.files.download(file=video)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(video_bytes)
            logger.info(f"[{index:02d}] ✅ Saved: {out_path}")
            return out_path

        except gapi_exceptions.ResourceExhausted:
            logger.error(f"\n[{index:02d}] 🛑 QUOTA EXHAUSTED (429). Stop and retry tomorrow.")
            raise
        except Exception as e:
            logger.error(f"[{index:02d}] ❌ Exception: {e}")
            return None
