"""OpenRouter provider routing for the text/JSON path.

Why this exists (measured 2026-11-11): OpenRouter's default routing balances
price against throughput, latency and reliability, and lands on the STANDARD
service tier for Google models. Every Google model we might use as a judge
offers a FLEX tier at exactly half the standard price:

  model                        flex         standard    priority
  google/gemini-4-hydrogen        1.000/5.000  2.000/10.000  3.600/18.000
  google/gemini-3.8-flash      0.375/1.875  0.750/3.750   1.350/6.750
  google/gemini-3.6-flash      0.375/1.875  0.750/3.750   1.350/6.750
  google/gemini-2.5-flash      0.150/1.250  0.300/2.500   0.540/4.500

($ per Mtok input/output). A QA judge call on our measured median profile
(39,616 prompt + 5,724 completion tokens) therefore costs:

  hydrogen  standard $0.1365 | argon  flex $0.0682
  3.8    standard $0.0512 | 3.8    flex $0.0256

Two ways to reach the flex tier, per OpenRouter's routing docs:

  provider: {"sort": "price"}   sorts endpoints by price, but does NOT by
                                 itself make flex endpoints eligible.
  model slug suffix ":floor"    a routing variant = price sort AND flex-tier
                                 eligible ("a superset of setting
                                 provider.sort to price").

MEASURED (2026-11-12, google/gemini-3.8-flash, tiny probe):
  standard (no routing)   provider "Google"           $2.775e-05   <- standard tier
  provider.sort = price   provider "Google AI Studio" $2.850e-05   <- STILL standard
  model slug ":floor"     provider "Google AI Studio" $1.2375e-05   <- FLEX (half)
  ":floor" + sort=price   provider "Google AI Studio" $1.4250e-05   <- FLEX (half)

So sort=price ALONE does not reach flex — it only reorders providers. The
":floor" model-slug suffix is what makes the flex tier ELIGIBLE. Both are
implemented here; ":floor" alone is sufficient.

This module keeps the two orthogonal knobs separate:
  AI_ROUTING_SORT            -> provider.sort ("price"/"throughput"/"latency")
  AI_ROUTING_ORDER           -> provider.order (explicit provider slug list)
  AI_ROUTING_MODEL_SUFFIX    -> model-slug variant (":floor" / ":nitro")

Empty (the default) means no routing preference at all, which preserves
OpenRouter's default behaviour exactly.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

VALID_SORTS = ("price", "throughput", "latency")
VALID_SUFFIXES = ("floor", "nitro")


def build_routing(sort: str = "", order: str = "",
                  model_suffix: str = "") -> dict:
    """Build the routing preferences for one OpenRouter client.

    Returns {"provider": {...} | None, "model_suffix": "floor" | ""}.
    Invalid values are ignored with a warning rather than raising — a bad
    env var must not break the pipeline.
    """
    provider: dict = {}

    if sort:
        if sort in VALID_SORTS:
            provider["sort"] = sort
        else:
            logger.warning("  ⚠️  AI_ROUTING_SORT=%r is not one of %s — ignored.",
                           sort, ", ".join(VALID_SORTS))

    if order:
        # Comma-separated provider slugs, e.g. "google-ai-studio/flex".
        slugs = [s.strip() for s in order.split(",") if s.strip()]
        if slugs:
            provider["order"] = slugs

    suffix = ""
    if model_suffix:
        if model_suffix in VALID_SUFFIXES:
            suffix = model_suffix
        else:
            logger.warning("  ⚠️  AI_ROUTING_MODEL_SUFFIX=%r is not one of %s — ignored.",
                           model_suffix, ", ".join(VALID_SUFFIXES))

    if not provider:
        provider = None
    elif provider:
        logger.info("  ↔ OpenRouter routing: %s%s", provider,
                    f" (model suffix ':{suffix}')" if suffix else "")

    return {"provider": provider, "model_suffix": suffix}


def routing_summary(routing: Optional[dict]) -> str:
    """One-line human summary (for logs and dumps)."""
    if not routing:
        return "default routing"
    parts = []
    if routing.get("provider"):
        parts.append(str(routing["provider"]))
    if routing.get("model_suffix"):
        parts.append(f":{routing['model_suffix']}")
    return " + ".join(parts) or "default routing"
