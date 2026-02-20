"""Tests for core/config.py — env parsing and fail-fast validation."""

import os
import importlib
import sys

import pytest


def _reload_config(monkeypatch, env: dict) -> object:
    """Set env vars, evict cached module, reimport, return fresh config."""
    # Patch env
    for key, val in env.items():
        monkeypatch.setenv(key, val)

    # Force re-import
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("core.config"):
            del sys.modules[mod_name]

    import core.config as cfg_module
    return cfg_module.config


# ---------------------------------------------------------------------------
# ALLOWED_TELEGRAM_IDS parsing
# ---------------------------------------------------------------------------


def test_allowed_telegram_ids_single(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "fake-key",
        "ALLOWED_TELEGRAM_IDS": "123456789",
    })
    assert cfg.allowed_telegram_ids == [123456789]


def test_allowed_telegram_ids_multiple(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "fake-key",
        "ALLOWED_TELEGRAM_IDS": "111, 222, 333",
    })
    assert cfg.allowed_telegram_ids == [111, 222, 333]


def test_allowed_telegram_ids_empty_string(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "fake-key",
        "ALLOWED_TELEGRAM_IDS": "",
    })
    assert cfg.allowed_telegram_ids == []


def test_allowed_telegram_ids_whitespace_only(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "fake-key",
        "ALLOWED_TELEGRAM_IDS": "   ",
    })
    assert cfg.allowed_telegram_ids == []


# ---------------------------------------------------------------------------
# ANTHROPIC_API_KEY fail-fast
# ---------------------------------------------------------------------------


def test_anthropic_api_key_fail_fast_on_missing(monkeypatch):
    """Missing ANTHROPIC_API_KEY must raise KeyError at import time."""
    monkeypatch.setenv("BOT_TOKEN", "fake-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("core.config"):
            del sys.modules[mod_name]

    with pytest.raises(KeyError):
        import core.config  # noqa: F401


def test_anthropic_api_key_accepted_when_set(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "ALLOWED_TELEGRAM_IDS": "",
    })
    assert cfg.anthropic_api_key == "sk-ant-test-key"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_defaults(monkeypatch):
    cfg = _reload_config(monkeypatch, {
        "BOT_TOKEN": "fake-token",
        "ANTHROPIC_API_KEY": "fake-key",
        "ALLOWED_TELEGRAM_IDS": "",
    })
    assert cfg.db_path == "data/career.db"
    assert cfg.profile_path == "identity/profile.json"
    assert cfg.log_level == "INFO"
    assert cfg.scoring_worker_interval == 10
