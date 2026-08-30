"""Loading .env, and the two rules that keep it safe."""

from __future__ import annotations

import os

import pytest

from hanko.config import key_status, load_env


_MANAGED = ("XAI_API_KEY", "RYO_API_KEY", "RYO_API_BASE")


@pytest.fixture()
def clean_env():
    """Clear the managed keys, and put the process back exactly as found.

    load_env writes to os.environ for real -- that is the point of it --
    so a test that calls it will leak into every test that runs after
    unless the original values are restored here.
    """
    saved = {name: os.environ.get(name) for name in _MANAGED}
    for name in _MANAGED:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def write(tmp_path, text: str):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_key_value_pairs(tmp_path, clean_env, monkeypatch):
    load_env(write(tmp_path, "XAI_API_KEY=abc123\n"))
    assert os.environ["XAI_API_KEY"] == "abc123"


def test_the_real_environment_wins(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "from-the-shell")
    loaded = load_env(write(tmp_path, "XAI_API_KEY=from-the-file\n"))
    # CI and deployment set things properly. A stale local file must never
    # quietly override them.
    assert os.environ["XAI_API_KEY"] == "from-the-shell"
    assert "XAI_API_KEY" not in loaded


def test_returns_names_never_values(tmp_path, clean_env):
    loaded = load_env(write(tmp_path, "XAI_API_KEY=supersecret\n"))
    assert loaded == ["XAI_API_KEY"]
    assert "supersecret" not in repr(loaded)


def test_skips_comments_blanks_and_empty_values(tmp_path, clean_env):
    loaded = load_env(
        write(
            tmp_path,
            "# a comment\n\nXAI_API_KEY=\nRYO_API_KEY=set\nnot a pair\n",
        )
    )
    # An unfilled placeholder is not a credential.
    assert loaded == ["RYO_API_KEY"]
    assert "XAI_API_KEY" not in os.environ


def test_strips_quotes(tmp_path, clean_env):
    load_env(write(tmp_path, 'XAI_API_KEY="quoted-value"\n'))
    assert os.environ["XAI_API_KEY"] == "quoted-value"


def test_a_missing_file_is_not_an_error(tmp_path, clean_env):
    assert load_env(tmp_path / "nope.env") == []


def test_key_status_reports_presence_only(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "supersecret")
    status = key_status("XAI_API_KEY", "RYO_API_KEY")
    assert status == {"XAI_API_KEY": True, "RYO_API_KEY": False}
    assert "supersecret" not in repr(status)
