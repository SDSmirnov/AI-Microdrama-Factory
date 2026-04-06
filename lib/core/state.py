"""ProjectState: persistent, thread-safe DAG pipeline progress tracker.

State lives in cinematic_render/pipeline_state.json.
All mutations are atomic (write-to-tmp + rename) and lock-protected.

Nested key paths navigate the stages dict tree, e.g.:
    state.is_done("screenplay", "ep_raw", 3)
    state.mark_done("screenplay", "ep_refined", 7)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.core.utils import atomic_write

logger = logging.getLogger(__name__)

_DONE = "done"
_FAILED = "failed"


class ProjectState:
    VERSION = 1

    def __init__(self, path: Path, data: dict | None = None):
        self._path = path
        self._data: dict = data if data is not None else {"version": self.VERSION, "stages": {}}
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path) -> "ProjectState":
        """Load state from disk; return empty state if missing or corrupt."""
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if raw.get("version") == cls.VERSION:
                    return cls(path, raw)
                logger.warning("⚠️  State file version mismatch at %s — starting fresh", path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("⚠️  Corrupt state file at %s: %s — starting fresh", path, exc)
        return cls(path)

    # ── Internal (callers must hold self._lock) ──────────────────────────────

    def _save(self) -> None:
        atomic_write(self._path, json.dumps(self._data, indent=2, ensure_ascii=False))

    def _navigate(self, keys: tuple, *, create: bool = False) -> dict | None:
        node = self._data.setdefault("stages", {})
        for k in keys:
            k = str(k)
            if create:
                node = node.setdefault(k, {})
            else:
                node = node.get(k)
                if not isinstance(node, dict):
                    return None
        return node

    # ── Public API ────────────────────────────────────────────────────────────

    def is_done(self, *keys: str | int) -> bool:
        with self._lock:
            node = self._navigate(keys)
            return node is not None and node.get("status") == _DONE

    def mark_done(self, *keys: str | int, **meta: Any) -> None:
        with self._lock:
            node = self._navigate(keys, create=True)
            node["status"] = _DONE
            node["completed_at"] = datetime.now(timezone.utc).isoformat()
            node.update({k: v for k, v in meta.items() if k not in ("status", "completed_at")})
            self._save()

    def mark_failed(self, *keys: str | int, error: str = "") -> None:
        with self._lock:
            node = self._navigate(keys, create=True)
            node["status"] = _FAILED
            node["failed_at"] = datetime.now(timezone.utc).isoformat()
            if error:
                node["error"] = error[:500]
            self._save()

    def reset(self, *keys: str | int) -> None:
        """Remove a node from state (marks it as not started)."""
        with self._lock:
            parent = self._navigate(keys[:-1], create=False) if len(keys) > 1 else self._data.get("stages", {})
            if isinstance(parent, dict):
                parent.pop(str(keys[-1]), None)
            self._save()

    # ── Screenplay-specific helpers ───────────────────────────────────────────

    def episodes_done(self) -> bool:
        return self.is_done("screenplay", "episodes")

    def mark_episodes_done(self, count: int) -> None:
        self.mark_done("screenplay", "episodes", count=count)

    def episode_raw_done(self, ep_id: int) -> bool:
        return self.is_done("screenplay", "ep_raw", ep_id)

    def mark_episode_raw_done(self, ep_id: int) -> None:
        self.mark_done("screenplay", "ep_raw", ep_id)

    def episode_refined_done(self, ep_id: int) -> bool:
        return self.is_done("screenplay", "ep_refined", ep_id)

    def mark_episode_refined_done(self, ep_id: int) -> None:
        self.mark_done("screenplay", "ep_refined", ep_id)
