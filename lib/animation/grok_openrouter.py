"""
GrokOpenRouterAnimator — video generation via OpenRouter (x-ai/grok-imagine-video-1.5).

Alternative to GrokAnimator (lib/animation/grok.py), which talks to xai_sdk directly;
this backend goes through OpenRouterLLM.generate_video() (async submit/poll/download
over OpenRouter's REST API), so it needs only OPENROUTER_API_KEY.

Prompt path (Item 3): shared structured builder; refs come from the Item 2
assembler on this animator's own project context. The old raw-dict prompt
(_build_prompt with ANIMATION_PROHIBITIONS / hardcoded genre+lens) is gone here.
"""
import hashlib
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.animation.base import BaseAnimator, clip_path_for_panel
from lib.animation.capabilities import caps_for, default_video_model, plan_clip
from lib.animation.refs import RefBite, assemble_refs, default_max_refs
from lib.animation.prompt_builder import build_acting, build_video_prompt
from lib.animation.voices import resolve_voice
from lib.llm import manual as manual_llm
from lib.llm.openrouter import OpenRouterLLM, build_video_payload

logger = logging.getLogger(__name__)

DEFAULT_DURATION = 6
DEFAULT_RESOLUTION = os.getenv('AI_VIDEO_RESOLUTION', '720p')
DEFAULT_ASPECT = os.getenv('AI_VIDEO_ASPECT', '9:16')
BATCH_SIZE = 4  # concurrent OpenRouter video jobs (each submits then polls for minutes)
POLL_INTERVAL = 10
TIMEOUT = 900

# Duration range for the DEFAULT model (model page: 1-15 s). The EFFECTIVE
# cap depends on the transport: reference-to-video is capped at 10 s
# (MEASURED: an 11 s request with input_references returns HTTP 400
# "Duration 11s exceeds the maximum allowed for reference-to-video, which
# is 10s"), while text/image modes run to the full 15 s. We use the refs
# transport, so 10 s is the real ceiling. lib/animation/capabilities.py
# owns these rules.
MIN_DURATION, MAX_DURATION = 1, 15

# last_frame passthrough on OpenRouter is UNVERIFIED (model page lists only
# frame_type "first_frame"). Flip this env to 1 only after the passthrough
# probe confirms it (GROK-VIDEO-PLAN probe 2 / Item 4). Reversed panels always
# skip the pin until the pilot verifies their _static/_end semantics.
SEND_LAST_FRAME_ENV = 'AI_OPENROUTER_LAST_FRAME'

# Item 9: identity stress-test action bank. Neutral, camera-readable
# actions only — no weapon/safety-trigger vocabulary (the point is
# identity persistence, not capability).
STRESS_ACTIONS = [
    "walks in and stops",
    "sits down",
    "laughs and covers their mouth",
    "pours a drink",
    "sets an object down on the surface in front of them",
    "leans against the wall and crosses their arms",
]

STRESS_IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "identity_same": {"type": "boolean",
                          "description": "True when the person in the clip is recognizable as the same person as the described reference character, while in action."},
        "note": {"type": "string", "description": "One sentence on what matched or drifted (face, build, age, clothing)."},
    },
    "required": ["identity_same", "note"],
}


def _clamp_duration(d, model: str = None, using_references: bool = True) -> int:
    """Clamp a requested duration to what the model will accept.

    `using_references` defaults to True because our transport is refs-only
    (Item 2), and reference mode has the 10 s cap.
    """
    try:
        d = int(d)
    except (TypeError, ValueError):
        d = DEFAULT_DURATION
    caps = caps_for(model or default_video_model())
    return caps.clamp_seconds(d, using_references)


class GrokOpenRouterAnimator(BaseAnimator):
    """
    Video generation via OpenRouter (x-ai/grok-imagine-video-1.5).

    Single-panel interface via animate(); batch interface via run_all().
    `project` supplies the ref catalog for the Item 2 assembler (character_info
    is loaded by the command layer); `llm` is injectable for tests.
    """

    def __init__(
        self,
        api_key: str,
        model: str = None,
        duration: int = DEFAULT_DURATION,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = None,
        batch_size: int = BATCH_SIZE,
        poll_interval: int = POLL_INTERVAL,
        timeout: int = TIMEOUT,
        project=None,
        llm: OpenRouterLLM = None,
        dry: bool = None,
        prompts: dict = None,
    ):
        model = model or default_video_model()
        self.llm = llm if llm is not None else OpenRouterLLM(
            api_key=api_key, text_model="", image_model="", video_model=model)
        self.duration = duration
        self.resolution = resolution or '720p'
        self.aspect_ratio = aspect_ratio or DEFAULT_ASPECT
        # The model id drives the capability envelope (duration cap, whether
        # references are accepted, which resolutions exist).
        self.model = model or default_video_model()
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.project = project
        # Prompt bundle (style/imagery/setting) for the STYLE PREFIX block.
        self.prompts = prompts or {}
        self._dry = os.getenv('DRY') == '1' if dry is None else dry
        self._send_last_frame = os.getenv(SEND_LAST_FRAME_ENV) == '1'
        if self._send_last_frame:
            # Probe 2 (2026-11-10): OpenRouter 400 "the provider integration for
            # model x-ai/grok-imagine-video-1.5 does not support last_frame
            # frame_images". The pin is x.ai-direct only (lib/animation/grok.py).
            logger.warning("    AI_OPENROUTER_LAST_FRAME=1 ignored: the OpenRouter "
                           "integration rejects last_frame (probe 2, 400). Use the "
                           "xai-direct grok.py backend for end-frame pins.")
            self._send_last_frame = False
        # Item 8a: per-scene spatial-map cache (computed once per run).
        self._spatial_cache = {}

    # ------------------------------------------------------------------
    # Refs + prompt (Items 2-3)
    # ------------------------------------------------------------------

    def _spatial_map(self, scene: dict) -> str:
        """Item 8a: per-scene spatial map, computed once per run."""
        if self.project is None or not scene:
            return ""
        sid = int(scene.get('scene_id', 0))
        if sid not in self._spatial_cache:
            from lib.animation.refs import _RefCatalog
            from lib.animation.prompt_builder import build_spatial_map
            self._spatial_cache[sid] = build_spatial_map(
                scene, _RefCatalog(self.project))
        return self._spatial_cache[sid]

    def _prepare(self, scene: dict, panel: dict, panels_dir: Path) -> Optional[dict]:
        """Resolve assets for one panel: refs (assembler), prompt (builder),
        duration clamp, optional end-frame pin. Returns None when the panel
        cannot be rendered (no first frame)."""
        scene_id = int(scene['scene_id'])
        panel_index = int(panel['panel_index'])
        start_path = panels_dir / f"{scene_id:03d}_{panel_index:02d}_static.png"
        if not start_path.exists():
            logger.warning("⚠️  Image not found: %s, skipping", start_path)
            return None
        end_path = panels_dir / f"{scene_id:03d}_{panel_index:02d}_end.png"

        max_refs = default_max_refs()
        bites: list[RefBite] = []
        if self.project is not None:
            bites = assemble_refs(panel, scene, panels_dir, self.project,
                                  max_refs=max_refs)
        # Prefer the assembler's first-frame bite when it exists.
        has_assembler_frame = bool(bites and bites[0].role == 'first_frame')
        if not has_assembler_frame:
            first_bite = RefBite(tag="<IMAGE_0>", png=start_path,
                                 role="first_frame", name=start_path.stem, descriptor="")
            bites = [first_bite] + [b for b in bites if b.role != 'first_frame']
            logger.debug("    first frame re-pinned from run_all path: %s", start_path)

        duration = _clamp_duration(panel.get('duration', self.duration))
        # Item 5b (OpenRouter route): prose voice descriptors bound to
        # character <IMAGE_N> tags; empty list when nothing to resolve.
        voices = resolve_voice(panel, bites)
        # Item 7b: acting contributions from ref JSONs; empty list when the
        # ref catalog carries none (EYE LIFE default still rendered).
        acting = build_acting(panel, bites,
                              getattr(self.project, 'character_info', {}) or {})
        # Item 8a: per-(scene, location) spatial map, computed once per run
        # and pasted verbatim as SPATIAL BLOCKING's first line.
        smap = self._spatial_map(scene)

        reference_images = [b.png for b in bites if b.role != 'first_frame' and b.png]
        last_frame = None
        if (end_path.exists() and self._send_last_frame
                and not panel.get('is_reversed')):
            last_frame = end_path
        elif end_path.exists() and panel.get('is_reversed') and self._send_last_frame:
            logger.info("    [s%dp%02d] is_reversed panel: last_frame pin skipped "
                        "until pilot verifies _static/_end semantics.",
                        scene_id, panel_index)

        # What the model will ACTUALLY accept. The screenwriter may ask for
        # 15 s, but reference mode caps at 10 s (measured 400), and some
        # models take no references at all.
        plan = plan_clip(
            model=self.model,
            requested_seconds=duration,
            resolution=self.resolution,
            aspect_ratio=self.aspect_ratio,
            n_reference_images=len(reference_images),
            wants_last_frame=last_frame is not None)
        for note in plan["notes"]:
            logger.info("    [s%dp%02d] %s", scene_id, panel_index, note)
        if not plan["using_references"]:
            reference_images = []
        duration = plan["duration"]
        prompt = build_video_prompt(panel, bites, voices, duration,
                                    acting=acting, spatial_map=smap,
                                    prompts=self.prompts)

        return {
            'start_path': start_path,
            'end_path': end_path if end_path.exists() else None,
            'last_frame': last_frame if plan["wants_last_frame"] else None,
            'reference_images': reference_images,
            'prompt': prompt,
            'duration': duration,
            'bites': bites,
            'plan': plan,
        }

    def master_shot(self, scene: dict, panels_dir: Path,
                    out_dir: Path) -> Optional[Path]:
        """Item 8b: 2s wide static-camera reference clip of the scene
        arrangement. First frame (the scene's first panel still) + location
        ref + in-frame character refs via the Item 2 assembler; one spatial
        map line (the compass line); no dialogue, no acting. Skip-if-exists
        on re-run. DRY=1 dumps the prompt + payload instead of submitting.
        """
        scene_id = int(scene.get('scene_id', 0))
        panels = sorted(scene.get('panels', []), key=lambda p: p['panel_index'])
        if not panels:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"master_{scene_id:03d}.mp4"
        if out_path.exists():
            logger.info("    [master s%03d] exists, skipping (delete it to "
                        "re-render).", scene_id)
            return None

        base = panels[0]
        start_path = panels_dir / f"{scene_id:03d}_{base['panel_index']:02d}_static.png"
        if not start_path.exists():
            logger.warning("    [master s%03d] first panel still missing: %s",
                           scene_id, start_path)
            return None

        # Dominant location + in-frame characters across the scene.
        locs = [loc for p in panels
                for loc in (p.get('location_references') or []) if loc]
        loc = max(set(locs), key=locs.count) if locs else None
        chars: list = []
        for p in panels:
            for a in (p.get('state') or {}).get('actors') or []:
                slug = a.get('visual_ref') or a.get('name', '')
                if a.get('in_frame') and slug and slug not in chars:
                    chars.append(slug)
        master_panel = {
            'panel_index': base['panel_index'],
            'duration': 2,
            'location_references': [loc] if loc else [],
            'references': [],
            'state': {'actors': [{'name': c, 'visual_ref': c,
                                  'in_frame': True} for c in chars]},
            'dialogue': '',
            'voiceover': '',
            'motion_intent': 'Master shot: establish the scene arrangement '
                             'once, static camera, nobody performs.',
            'motion_prompt': 'Static wide shot of the full location with the '
                             'in-frame characters holding their positions; '
                             'only ambient life (breathing, micro-sway).',
            'visual_start': '[SCALE] WS 24mm eye-level cam@[center]\n'
                            'MASTER SHOT for editorial geography only; not a '
                            'story panel',
            'is_reversed': False,
        }

        max_refs = default_max_refs()
        bites: list[RefBite] = []
        if self.project is not None:
            bites = assemble_refs(master_panel, scene, panels_dir, self.project,
                                  max_refs=max_refs)
        if not bites or bites[0].role != 'first_frame':
            bites = [RefBite(tag="<IMAGE_0>", png=start_path,
                             role="first_frame", name=start_path.stem,
                             descriptor="")] + \
                    [b for b in bites if b.role != 'first_frame']

        # One spatial map line: the GEOMETRY compass line of the scene map.
        smap_lines = [l for l in self._spatial_map(scene).splitlines()
                      if l.startswith('GEOMETRY')]
        prompt = build_video_prompt(master_panel, bites, [], 2,
                                    spatial_map=smap_lines[0] if smap_lines
                                    else None, prompts=self.prompts)
        prep = {
            'start_path': start_path,
            'end_path': None,
            'last_frame': None,
            'reference_images': [b.png for b in bites
                                 if b.role != 'first_frame' and b.png],
            'prompt': prompt,
            'duration': 2,
            'bites': bites,
        }
        if self._dry:
            self._dry_dump_master(scene_id, prep)
            return None
        return self._submit(prep, out_path, 0)

    def _dry_dump_master(self, scene_id: int, prep: dict) -> None:
        payload = build_video_payload(
            prompt=prep['prompt'], start_image=prep['start_path'],
            duration=prep['duration'],
            resolution=prep.get('plan', {}).get('resolution', self.resolution),
            aspect_ratio=prep.get('plan', {}).get('aspect_ratio', self.aspect_ratio),
            last_frame=None, reference_images=prep['reference_images'],
        )
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        manual_llm._OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = manual_llm._OUTPUT_DIR / f"master_s{scene_id:03d}_{ts}.md"
        path.write_text(
            "# GROK OPENROUTER DRY (master shot)\n\n"
            f"scene {scene_id}  |  duration={payload['duration']}s  |  "
            f"references: {len(payload['input_references'])}\n\n"
            f"## REFS\n" + "\n".join(
                f"- {b.tag} ({b.role}) {b.name} -> {b.png}"
                for b in prep['bites'])
            + "\n\n## PROMPT\n" + prep['prompt']
            + "\n\n# PAYLOAD\n"
            + json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding='utf-8')
        logger.info("📝 DRY dump -> %s", path)

    def stress_refs(self, name: str, gens, out_dir: Path,
                    metadata: dict = None) -> Optional[Path]:
        """Item 9: identity stress test. Generates `gens` (default 5)
        4s clips of `name` performing neutral actions from STRESS_ACTIONS
        (cycled), using the character's primary ref PNG as the start image
        plus their default location ref (most common location across the
        character's in-frame panels in `metadata`). Writes
        {out_dir}/{slug}_{NN}.mp4 + one jsonl report line per clip (a
        report, not a second source of truth). DRY=1 dumps instead.
        """
        gens = int(gens) if gens else 5
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")

        char_png = None
        if self.project is not None:
            from lib.animation.refs import _RefCatalog
            info, png = _RefCatalog(self.project).lookup(name)
            char_png = png
        if char_png is None:
            logger.warning("    [stress %s] no ref PNG found; aborting.", name)
            return None

        location = self._default_location(name, metadata)
        ref_dirs = out_dir  # stress clips have no panel stills

        report_path = out_dir / "report.jsonl"
        for gen in range(1, gens + 1):
            action = STRESS_ACTIONS[(gen - 1) % len(STRESS_ACTIONS)]
            panel = {
                'panel_index': gen,
                'duration': 4,
                'location_references': [location] if location else [],
                'references': [],
                'state': {'actors': [{'name': name, 'visual_ref': name,
                                      'in_frame': True}]},
                'dialogue': '',
                'voiceover': '',
                'motion_intent': f'Identity stress test: the character '
                                 f'{action}. One continuous take.',
                'motion_prompt': f'The character {action}, full natural body '
                                 f'motion, face clearly visible throughout.',
                'visual_start': '[SCALE] MS 40mm eye-level cam@[center]\n'
                                'IDENTITY STRESS TEST clip, not a story panel',
                'is_reversed': False,
            }
            bites: list[RefBite] = []
            if self.project is not None:
                bites = assemble_refs(panel, {'scene_id': 0}, ref_dirs,
                                      self.project,
                                      max_refs=default_max_refs())
            prompt = build_video_prompt(panel, bites, [], 4, prompts=self.prompts)
            out_path = out_dir / f"{slug}_{gen:02d}.mp4"
            rec = {"name": name, "gen": gen, "action": action,
                   "prompt_hash": hashlib.sha256(
                       prompt.encode()).hexdigest()[:16],
                   "clip": str(out_path)}
            # The character ref IS the start image (<IMAGE_0> in refs-only
            # mode) — never also sent as an input_reference.
            ref_pngs = [b.png for b in bites
                        if b.role != 'first_frame' and b.png
                        and b.png != char_png]
            if self._dry:
                self._dry_dump_stress(slug, gen, prompt, char_png, ref_pngs)
                continue
            video_bytes = self.llm.generate_video(
                prompt=prompt, start_image=char_png, last_frame=None,
                reference_images=ref_pngs,
                duration=4, resolution=self.resolution,
                aspect_ratio=self.aspect_ratio,
                poll_interval=self.poll_interval, timeout=self.timeout)
            out_path.write_bytes(video_bytes)
            with report_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            logger.info("    [stress %s] gen %02d saved: %s", name, gen,
                        out_path.name)
        if self._dry:
            return None
        return report_path

    def _default_location(self, name: str, metadata: dict) -> Optional[str]:
        """The character's default location: the most common
        location_references across their in-frame panels."""
        if not metadata:
            logger.info("    [stress %s] no metadata: no location ref in "
                        "stress prompts.", name)
            return None
        counts: dict = {}
        for scene in metadata.get('scenes', []):
            for p in scene.get('panels', []):
                actors = (p.get('state') or {}).get('actors') or []
                if any((a.get('visual_ref') or a.get('name')) == name
                       and a.get('in_frame') for a in actors):
                    for loc in p.get('location_references') or []:
                        counts[loc] = counts.get(loc, 0) + 1
        if not counts:
            logger.info("    [stress %s] no in-frame panels in metadata: "
                        "no location ref in stress prompts.", name)
            return None
        return max(counts, key=counts.get)

    def judge_stress(self, name: str, out_dir: Path, vision_llm) -> None:
        """Item 9 pass criterion: recognizable as the same person across
        all N generations while in action. Appends `identity_same` +
        `note` to the matching report lines. Vision-QA backend required;
        without one the report is left for human review (logged)."""
        report_path = out_dir / "report.jsonl"
        if not report_path.exists():
            logger.warning("    [stress %s] no report to judge.", name)
            return
        records = [json.loads(l) for l in
                   report_path.read_text(encoding='utf-8').splitlines() if l]
        try:
            for rec in records:
                clip = Path(rec["clip"])
                if not clip.exists():
                    rec["identity_same"] = None
                    rec["note"] = "clip missing; human review required"
                    continue
                verdict = vision_llm.analyze_video(
                    video=clip,
                    prompt=("Does the person performing the action in this "
                            f"clip read as the same character ({name}) "
                            "across takes: same face, build, age, clothing? "
                            "Judge identity persistence while in motion."),
                    schema=STRESS_IDENTITY_SCHEMA)
                if isinstance(verdict, dict) and "text" in verdict:
                    verdict = json.loads(verdict["text"])
                rec["identity_same"] = bool(verdict.get("identity_same"))
                rec["note"] = verdict.get("note", "")
        except NotImplementedError as e:
            logger.warning("    [stress %s] vision backend cannot analyze "
                           "video (%s) — human review of the clips is the "
                           "fallback pass criterion.", name, e)
            return
        with report_path.open('w', encoding='utf-8') as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        same = sum(1 for r in records if r.get("identity_same"))
        logger.info("    [stress %s] identity held in %d/%d clips.", name,
                    same, len(records))

    def _dry_dump_stress(self, slug: str, gen: int, prompt: str,
                         char_png, ref_pngs: list) -> None:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        manual_llm._OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = manual_llm._OUTPUT_DIR / f"stress_{slug}_{gen:02d}_{ts}.md"
        path.write_text(
            "# GROK OPENROUTER DRY (stress-refs)\n\n"
            f"stress {slug} gen {gen:02d}  |  start_image: {char_png}  |  "
            f"refs: {ref_pngs}\n\n## PROMPT\n{prompt}\n",
            encoding='utf-8')
        logger.info("📝 DRY dump -> %s", path)

    def _dry_dump(self, scene_id: int, panel_index: int, prep: dict) -> Path:
        """DRY=1: write the exact prompt + request payload, call nothing."""
        payload = build_video_payload(
            prompt=prep['prompt'], start_image=prep['start_path'],
            duration=prep['duration'],
            resolution=prep.get('plan', {}).get('resolution', self.resolution),
            aspect_ratio=prep.get('plan', {}).get('aspect_ratio', self.aspect_ratio),
            last_frame=prep['last_frame'],
            reference_images=prep['reference_images'],
        )
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        manual_llm._OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = manual_llm._OUTPUT_DIR / f"grok-openrouter_s{scene_id:03d}_p{panel_index:02d}_{ts}.md"
        body = (
            f"# GROK OPENROUTER DRY\n\n"
            f"scene {scene_id} panel {panel_index}  |  duration={payload['duration']}s\n"
            f"references: {len(payload['input_references'])}  |  "
            f"last_frame: {'YES' if prep['last_frame'] else 'no'}\n\n"
            f"## REFS\n" + "\n".join(
                f"- {b.tag} ({b.role}) {b.name} -> {b.png}" for b in prep['bites'])
            + "\n\n## PROMPT\n" + prep['prompt']
            + "\n\n# PAYLOAD\n" + json.dumps(payload, indent=2, ensure_ascii=False)
            + "\n"
        )
        path.write_text(body, encoding='utf-8')
        logger.info("📝 DRY dump -> %s", path)
        return path

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _submit(self, prep: dict, out_path: Path, index: int) -> Optional[Path]:
        plan = prep.get('plan', {}) or {}
        video_bytes = self.llm.generate_video(
            prompt=prep['prompt'],
            start_image=prep['start_path'],
            last_frame=prep['last_frame'],
            reference_images=prep['reference_images'],
            duration=prep['duration'],
            resolution=plan.get('resolution', self.resolution),
            aspect_ratio=plan.get('aspect_ratio', self.aspect_ratio),
            poll_interval=self.poll_interval,
            timeout=self.timeout,
        )
        out_path.write_bytes(video_bytes)
        logger.info("[%02d] ✅ Saved: %s", index, out_path.name)
        return out_path

    def animate(
        self,
        start_path: Path,
        end_path: Optional[Path],
        meta: dict,
        index: int,
        out_dir: Path,
    ) -> Optional[Path]:
        """Animate a single panel (blocking: submits, polls, downloads).

        Prompt is built from metadata alone (no scene context in this legacy
        entry point); run_all() is the refs-aware path.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = clip_path_for_panel(start_path, out_dir)

        if out_path.exists() and out_path.stat().st_size > 0:
            logger.info(f"[{index:02d}] ⏭️  Skipping: {out_path.name} already exists.")
            return out_path

        prep = {'start_path': start_path, 'end_path': end_path,
                'last_frame': end_path if (end_path and self._send_last_frame
                                           and not meta.get('is_reversed')) else None,
                'reference_images': [], 'prompt': build_video_prompt(meta, [], [], _clamp_duration(meta.get('duration', self.duration)), prompts=self.prompts),
                'duration': _clamp_duration(meta.get('duration', self.duration)),
                'bites': []}
        if self._dry:
            scene_id = meta.get('scene_id') or 0
            self._dry_dump(scene_id, meta.get('panel_index', 0), prep)
            return None

        try:
            return self._submit(prep, out_path, index)
        except Exception as e:
            logger.error(f"[{index:02d}] ❌ {e}")
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

        Reads *_static.png panel images, assembles refs + structured prompt
        per panel (Items 2-3), and runs up to batch_size video jobs
        concurrently (each job blocks on its own submit/poll/download cycle).
        With DRY=1, writes prompt+payload dumps and performs no API calls.
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
                prep = self._prepare(scene, panel, Path(panels_dir))
                if prep is None:
                    continue
                out_path = out_dir / f"clip_{scene_id:02d}_{panel_id:03d}.mp4"
                if out_path.exists() and out_path.stat().st_size > 0:
                    logger.info(f"SKIPPED {out_path.name}")
                    continue
                tasks.append((scene_id, panel_id, prep, out_path))

        if not tasks:
            logger.info("No panels to animate.")
            return

        if self._dry:
            for scene_id, panel_id, prep, _ in tasks:
                self._dry_dump(scene_id, panel_id, prep)
            logger.info("📝 DRY: %d panel dump(s) written, no API calls.", len(tasks))
            return

        logger.info("🎬 Animating %d panel(s), %d concurrent job(s)...",
                    len(tasks), self.batch_size)
        failures: list[tuple[str, BaseException]] = []
        fatal = threading.Event()

        def job(prep, out_path, i):
            if fatal.is_set():
                return None
            try:
                return self._submit(prep, out_path, i)
            except (SystemExit, KeyboardInterrupt):
                fatal.set()  # set by the worker: the main thread is too late to stop the next submit
                raise

        with ThreadPoolExecutor(max_workers=self.batch_size) as executor:
            futures = {
                executor.submit(job, prep, out_path, i): out_path
                for i, (sid, pid, prep, out_path) in enumerate(tasks)
            }
            for future in as_completed(futures):
                out_path = futures[future]
                exc = future.exception()
                if exc is None:
                    continue
                if not isinstance(exc, Exception):
                    # SystemExit/KeyboardInterrupt must stop the run, not be
                    # downgraded to a log line.
                    raise exc
                failures.append((out_path.name, exc))
                logger.error(f"❌ {out_path.name}: {exc}")

        if failures:
            names = ", ".join(name for name, _ in failures[:5])
            more = "" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"
            raise RuntimeError(
                f"{len(failures)}/{len(tasks)} clip(s) failed: {names}{more}")

        logger.info(f"\n✅ Done. Clips in {out_dir}/")
