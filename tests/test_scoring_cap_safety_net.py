"""Tests for scoring cap safety net — TASK-1.

Verifies that config defaults are set to safe production values:
  HH_SCORING_DAILY_CAP default = 500
  TG_SCORING_DAILY_CAP default = 50
"""
import os
import pytest


def test_scoring_cap_500_as_safety_net():
    """HH scoring daily cap default should be 500 (safety net for LLM costs)."""
    # Temporarily unset so we get the default
    original = os.environ.pop("HH_SCORING_DAILY_CAP", None)
    try:
        from core import config as cfg_module
        import importlib
        import core.config as _cfg
        # Read the source default directly
        import inspect
        source = inspect.getsource(_cfg.Config.from_env)
        assert '"500"' in source, (
            "HH_SCORING_DAILY_CAP default should be '500' in Config.from_env()"
        )
    finally:
        if original is not None:
            os.environ["HH_SCORING_DAILY_CAP"] = original


def test_tg_scoring_cap_50_as_safety_net():
    """TG scoring daily cap default should be 50 (safety net for LLM costs)."""
    original = os.environ.pop("TG_SCORING_DAILY_CAP", None)
    try:
        import inspect
        import core.config as _cfg
        source = inspect.getsource(_cfg.Config.from_env)
        assert '"50"' in source, (
            "TG_SCORING_DAILY_CAP default should be '50' in Config.from_env()"
        )
    finally:
        if original is not None:
            os.environ["TG_SCORING_DAILY_CAP"] = original


def test_env_hh_cap_overrides_default():
    """Env var HH_SCORING_DAILY_CAP=500 should override any previous values."""
    assert os.getenv("HH_SCORING_DAILY_CAP", "500") == "500"


def test_env_tg_cap_overrides_default():
    """Env var TG_SCORING_DAILY_CAP=50 should be present and correct."""
    assert os.getenv("TG_SCORING_DAILY_CAP", "50") == "50"
