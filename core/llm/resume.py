"""Shared resume loader for LLM prompts.

Provides mtime-based caching keyed by path: the file is read once per
unique path and cached until the file's modification time changes.
No bot restart is required when resume.md is edited — the next call
re-reads the file automatically.

Usage:
    from core.llm.resume import get_resume_text
    text = get_resume_text(config.resume_path) or "(резюме не предоставлено)"
"""

import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# {path: (text, mtime)} — keyed by path so multiple paths coexist safely.
# Thread-safety is not a concern: this is async single-threaded code.
_cache: Dict[str, Tuple[str, Optional[float]]] = {}

_DEFAULT_MAX_CHARS = 20_000


def get_resume_text(path: str, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """Load resume from *path* with mtime-based caching.

    Re-reads the file automatically when its mtime changes (e.g. after edit).
    Returns empty string on any failure — callers should substitute a
    fallback placeholder rather than raising.

    Args:
        path: Absolute or relative path to the resume file.
        max_chars: Maximum characters to return (content truncated if longer).
                   Default 20 000 chars — keeps prompt within reasonable bounds.

    Returns:
        Resume text (possibly truncated), or empty string on failure.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        logger.warning(
            "Resume file not found at %r — continuing without resume context", path
        )
        _cache[path] = ("", None)
        return ""

    cached_text, cached_mtime = _cache.get(path, ("", None))
    if cached_mtime == mtime:
        return cached_text

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception as exc:
        logger.warning(
            "Failed to read resume file %r: %s — continuing without resume context",
            path,
            exc,
        )
        _cache[path] = ("", mtime)
        return ""

    text = text[:max_chars]
    _cache[path] = (text, mtime)
    logger.info("Resume loaded/refreshed from %r (%d chars)", path, len(text))
    return text
