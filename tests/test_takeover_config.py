import textwrap
from pathlib import Path

from autoservice.takeover_config import (
    TakeoverConfig, DEFAULT_TAKEOVER_CONFIG, load_takeover_config,
)


def test_default_values():
    assert DEFAULT_TAKEOVER_CONFIG.idle_timeout_ms == 30_000
    assert DEFAULT_TAKEOVER_CONFIG.warning_ms == 5_000
    assert DEFAULT_TAKEOVER_CONFIG.offline_grace_ms == 30_000


def test_load_from_dict_overrides_defaults():
    raw = {"takeover": {"idle_timeout_ms": 5000, "warning_ms": 1000}}
    cfg = load_takeover_config(raw)
    assert cfg.idle_timeout_ms == 5000
    assert cfg.warning_ms == 1000
    assert cfg.offline_grace_ms == 30_000  # default preserved


def test_load_from_missing_section_returns_default():
    cfg = load_takeover_config({})
    assert cfg == DEFAULT_TAKEOVER_CONFIG


def test_load_from_none_returns_default():
    cfg = load_takeover_config(None)
    assert cfg == DEFAULT_TAKEOVER_CONFIG


def test_load_from_file(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        takeover:
          idle_timeout_ms: 7000
          warning_ms: 2000
          offline_grace_ms: 10000
    """))
    cfg = load_takeover_config(p)
    assert cfg.idle_timeout_ms == 7000
    assert cfg.warning_ms == 2000
    assert cfg.offline_grace_ms == 10000


def test_load_from_missing_file_returns_default(tmp_path: Path):
    cfg = load_takeover_config(tmp_path / "does-not-exist.yaml")
    assert cfg == DEFAULT_TAKEOVER_CONFIG


def test_load_from_dict_with_invalid_string_falls_back():
    """Non-numeric string in YAML should fall back to default, not crash."""
    raw = {"takeover": {"idle_timeout_ms": "not_a_number"}}
    cfg = load_takeover_config(raw)
    assert cfg.idle_timeout_ms == DEFAULT_TAKEOVER_CONFIG.idle_timeout_ms


def test_load_from_dict_with_negative_value_falls_back():
    """Negative timeout is semantically invalid → default."""
    raw = {"takeover": {"warning_ms": -500}}
    cfg = load_takeover_config(raw)
    assert cfg.warning_ms == DEFAULT_TAKEOVER_CONFIG.warning_ms


def test_load_from_dict_with_float_coerces_to_int():
    """YAML often yields floats (5000.0) — should coerce cleanly."""
    raw = {"takeover": {"idle_timeout_ms": 7000.0}}
    cfg = load_takeover_config(raw)
    assert cfg.idle_timeout_ms == 7000
    assert isinstance(cfg.idle_timeout_ms, int)
