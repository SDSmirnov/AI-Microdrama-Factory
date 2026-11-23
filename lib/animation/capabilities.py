"""Video model capabilities — what each model ACTUALLY accepts.

The repo was written when video models did simple I2V: one start frame,
optionally an end frame, a fixed ~6 s clip. The models have moved on, and
the OLD assumptions are now actively wrong in places.

MEASURED / DOCUMENTED FACTS (2026-11-12):

  x-ai/grok-imagine-video-1.5      1-15 s, 480p/720p/1080p, first_frame
  x-ai/grok-imagine-video-1.5-lite 1-15 s, 480p/720p/1080p, first_frame
                                   $0.02/s 480p, $0.03/s 720p (vs
                                   grok 1.5 at $0.08/s / $0.14/s)
  x-ai/grok-imagine-video          1-15 s, 480p/720p, first_frame
  bytedance/seedance-2.0           4-15 s, first_frame AND last_frame,
                                   1080p AND 4K, seed: true

  REFERENCE MODE IS CAPPED AT 10 s. MEASURED: an 11 s request with
  input_references on x-ai/grok-imagine-video returns
      HTTP 400 "Duration 11s exceeds the maximum allowed for
      reference-to-video, which is 10s."
  Text and image (frame_images) modes run to the full 15 s.

  LITE DOES NOT ACCEPT REFERENCES. MEASURED: `input_references is not
  supported for this model` (HTTP 400) on
  x-ai/grok-imagine-video-1.5-lite, while `frame_images` with
  first_frame works (1 s 480p, $0.03). Lite is therefore a
  first-frame-only model: it cannot carry our character/location
  reference library.

This module is the single place that knows those rules, so the animator
clamps to what the model will actually accept instead of sending a
request that 400s mid-run.
"""
from dataclasses import dataclass, field

# Reference-to-video caps are PER MODEL, not global.
#
# MEASURED 2026-11-12 on OpenRouter: x-ai/grok-imagine-video with
# input_references at 11 s -> HTTP 400 "Duration 11s exceeds the maximum
# allowed for reference-to-video, which is 10s."
#
# x.ai's own docs (docs.x.ai/.../reference-to-video) give the per-model
# table:
#     grok-imagine-video-1.5   reference-to-video: up to 15 s
#     grok-imagine-video      reference-to-video: up to 10 s
#
# The measured 400 matches the documented older-model cap, so OpenRouter
# does enforce x.ai's per-model limit. The 1.5 model's 15 s reference
# limit is therefore taken from the vendor doc and is NOT independently
# measured on OpenRouter - see probes/probe_ref_duration.py. The animator
# clamps at request time regardless, so an over-optimistic ceiling costs
# a shortened clip, never a 400.
REF_MODE_MAX_SECONDS = 15          # grok-imagine-video-1.5 (vendor doc)
REF_MODE_MAX_SECONDS_OLD = 10     # grok-imagine-video (MEASURED 400)


@dataclass(frozen=True)
class VideoModelCaps:
    """What one video model accepts."""

    slug: str
    min_seconds: int
    max_seconds: int
    resolutions: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    supports_input_references: bool = True
    supports_frame_images: bool = True
    supports_last_frame: bool = False
    # Longest clip in REFERENCE mode (input_references). Differs per model:
    # grok-imagine-video-1.5 allows 15 s, the older grok-imagine-video 10 s.
    ref_max_seconds: int = REF_MODE_MAX_SECONDS
    # price per second at each resolution, USD
    per_second: dict[str, float] = field(default_factory=dict)
    # price per input image, USD
    per_image: float = 0.01

    def clamp_seconds(self, seconds: int, using_references: bool) -> int:
        """Clamp a requested duration to what this model accepts.

        `using_references` matters: reference mode has its own (lower) cap.
        """
        hi = self.max_seconds
        if using_references and self.supports_input_references:
            hi = min(hi, self.ref_max_seconds)
        return max(self.min_seconds, min(int(seconds), hi))

    def supports_resolution(self, res: str) -> bool:
        return res in self.resolutions

    def supports_aspect(self, ar: str) -> bool:
        return ar in self.aspect_ratios


# Built from the OpenRouter video models API (GET /api/v1/videos/models),
# fetched 2026-11-12. Kept as a literal so the pipeline works offline.
MODELS: dict[str, VideoModelCaps] = {
    "x-ai/grok-imagine-video-1.5": VideoModelCaps(
        slug="x-ai/grok-imagine-video-1.5",
        min_seconds=1, max_seconds=15,
        resolutions=("480p", "720p", "1080p"),
        aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
        supports_input_references=True,
        supports_frame_images=True,
        supports_last_frame=False,
        # Vendor doc: 1.5 allows up to 15 s in reference mode.
        ref_max_seconds=REF_MODE_MAX_SECONDS,
        per_second={"480p": 0.08, "720p": 0.14, "1080p": 0.25},
        per_image=0.01),
    "x-ai/grok-imagine-video-1.5-lite": VideoModelCaps(
        slug="x-ai/grok-imagine-video-1.5-lite",
        min_seconds=1, max_seconds=15,
        resolutions=("480p", "720p", "1080p"),
        aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
        # MEASURED: input_references -> HTTP 400 "not supported for this
        # model". first_frame via frame_images works.
        supports_input_references=False,
        supports_frame_images=True,
        supports_last_frame=False,
        ref_max_seconds=15,
        per_second={"480p": 0.02, "720p": 0.03, "1080p": 0.14},
        per_image=0.01),
    # The OLDER grok-imagine-video is the cheapest reference-capable model
    # we have: $0.05/s at 480p and $0.07/s at 720p, and its input images
    # cost $0.002 each (vs $0.01 for 1.5). MEASURED: 3 s 480p with one
    # reference cost $0.152 = 3 x $0.05 + 1 x $0.002 exactly.
    # For an episode (45 clips, 235 s, 1 first frame + 2.58 refs each)
    # that is $12.07 at 480p vs grok 1.5's $20.41 - 41 % off the video
    # line, which is 66-77 % of episode cost.
    "x-ai/grok-imagine-video": VideoModelCaps(
        slug="x-ai/grok-imagine-video",
        min_seconds=1, max_seconds=15,
        resolutions=("480p", "720p"),
        aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
        supports_input_references=True,
        supports_frame_images=True,
        supports_last_frame=False,
        # MEASURED 400 at 11 s.
        ref_max_seconds=REF_MODE_MAX_SECONDS_OLD,
        per_second={"480p": 0.05, "720p": 0.07},
        per_image=0.002),
    "bytedance/seedance-2.0": VideoModelCaps(
        slug="bytedance/seedance-2.0",
        min_seconds=4, max_seconds=15,
        resolutions=("480p", "720p", "1080p", "4K"),
        aspect_ratios=("1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"),
        supports_input_references=True,
        supports_frame_images=True,
        # The OpenRouter model record lists BOTH first_frame and last_frame
        # for this model - the only one in our set that does.
        supports_last_frame=True,
        # OpenRouter lists durations 4-15 s with no separate reference cap.
        ref_max_seconds=15,
        per_second={"480p": 0.071, "720p": 0.153},
        per_image=0.0),
    "bytedance/seedance-2.0-mini": VideoModelCaps(
        slug="bytedance/seedance-2.0-mini",
        min_seconds=4, max_seconds=15,
        resolutions=("480p", "720p"),
        aspect_ratios=("1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"),
        supports_input_references=True,
        supports_frame_images=True,
        supports_last_frame=False,
        ref_max_seconds=15,
        per_second={"480p": 0.0355},
        per_image=0.0),
}


def default_video_model() -> str:
    """The video model this project will use.

    Read at CALL time, not import time: the env var can be set after the
    module is imported, and a value frozen at import would silently
    disagree with the animator's own choice.
    """
    import os
    return os.getenv("AI_VIDEO_MODEL", "x-ai/grok-imagine-video-1.5")


def caps_for(model: str) -> VideoModelCaps:
    """Capabilities for a model slug, with a conservative fallback.

    An unknown model gets the safest possible envelope: the reference-mode
    10 s cap (we use the refs transport) and 480p/720p, because a request
    outside a model's envelope is a 400 and a 400 mid-run is a dead clip.
    """
    if model in MODELS:
        return MODELS[model]
    # A bare id ("grok-imagine-video-1.5") or a provider-prefixed one.
    for slug, caps in MODELS.items():
        if model == slug or model == slug.split("/", 1)[-1]:
            return caps
    return VideoModelCaps(
        slug=model,
        min_seconds=1, max_seconds=REF_MODE_MAX_SECONDS_OLD,
        resolutions=("480p", "720p"),
        aspect_ratios=("9:16", "16:9", "1:1"),
        supports_input_references=True,
        supports_frame_images=True,
        supports_last_frame=False,
        ref_max_seconds=REF_MODE_MAX_SECONDS_OLD,
        per_second={"480p": 0.08, "720p": 0.14},
        per_image=0.01)


def plan_clip(model: str, requested_seconds: int, resolution: str,
              aspect_ratio: str, n_reference_images: int,
              wants_last_frame: bool = False) -> dict:
    """Work out what to actually send for one clip.

    Returns the adjusted request plus the reasons, so the caller can log
    what it changed instead of silently shipping a different clip than the
    screenwriter asked for.
    """
    caps = caps_for(model)
    notes: list[str] = []

    using_refs = n_reference_images > 0
    if using_refs and not caps.supports_input_references:
        notes.append(
            f"{caps.slug} does not accept input_references (measured 400) "
            "- dropping the reference library and using first_frame only.")
        using_refs = False
        n_reference_images = 0

    seconds = caps.clamp_seconds(requested_seconds, using_refs)
    if seconds != requested_seconds:
        why = ("reference-to-video caps at 10 s" if using_refs
               else f"model caps at {caps.max_seconds} s")
        notes.append(f"duration {requested_seconds}s -> {seconds}s ({why})")

    if not caps.supports_resolution(resolution):
        fallback = "720p" if "720p" in caps.resolutions else caps.resolutions[0]
        notes.append(f"resolution {resolution} -> {fallback} (not supported)")
        resolution = fallback

    if not caps.supports_aspect(aspect_ratio):
        fallback = "9:16" if "9:16" in caps.aspect_ratios else caps.aspect_ratios[0]
        notes.append(f"aspect {aspect_ratio} -> {fallback} (not supported)")
        aspect_ratio = fallback

    if wants_last_frame and not caps.supports_last_frame:
        notes.append("last_frame is not supported by this model - dropped.")
        wants_last_frame = False

    return {
        "model": caps.slug,
        "duration": seconds,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "using_references": using_refs,
        "n_reference_images": n_reference_images,
        "wants_last_frame": wants_last_frame,
        "notes": notes,
    }


def estimate_clip_cost(model: str, seconds: int, resolution: str,
                       n_reference_images: int) -> float:
    """What one clip will cost, from the model's own price list.

    `n_reference_images` counts EVERY input image, the first frame
    included - the models charge per image input, not per reference.
    """
    caps = caps_for(model)
    per_sec = caps.per_second.get(resolution)
    if per_sec is None:
        raise ValueError(f"No price for {model} at {resolution}; known: {sorted(caps.per_second)}")
    return seconds * per_sec + n_reference_images * caps.per_image


def estimate_episode_cost(model: str, panels, resolution: str,
                           n_reference_images: float) -> dict:
    """Cost of a whole episode from a list of panel durations."""
    seconds = sum(panels)
    images = len(panels) * (1 + n_reference_images)
    total = estimate_clip_cost(model, seconds, resolution, images)
    return {
        "model": model,
        "resolution": resolution,
        "seconds": seconds,
        "images": images,
        "total": total,
        "per_minute": total / (seconds / 60.0) if seconds else 0.0,
        "per_panel": total / len(panels) if panels else 0.0,
    }
