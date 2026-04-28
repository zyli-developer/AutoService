import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    yield


def test_cors_origins_default_has_localhost_range(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "http://localhost:5173" in wg._CORS_ORIGINS
    assert "http://localhost:5179" in wg._CORS_ORIGINS


def test_cors_env_extra_single(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "https://autoservice.ezagent.chat")
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://autoservice.ezagent.chat" in wg._CORS_ORIGINS


def test_cors_env_extra_multi(monkeypatch):
    monkeypatch.setenv(
        "CORS_EXTRA_ORIGINS",
        "https://foo.example, https://bar.example",
    )
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://foo.example" in wg._CORS_ORIGINS
    assert "https://bar.example" in wg._CORS_ORIGINS


def test_cors_env_extra_ignores_empty_entries(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "  , https://a,  ,")
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://a" in wg._CORS_ORIGINS
    assert "" not in wg._CORS_ORIGINS
