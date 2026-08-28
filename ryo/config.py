"""Loading secrets from a local .env file.

Deliberately tiny and dependency-free. Two rules:

  A variable already present in the real environment always wins. CI and
  deployment set things properly; a stale local file must never quietly
  override them.

  Nothing here logs, prints, or returns a value. Keys reach the adapters
  through os.environ and nowhere else, so a secret cannot end up in a
  snapshot, a decision record, or a traceback.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | os.PathLike[str] = ".env") -> list[str]:
    """Load KEY=value lines into os.environ. Returns the names it set.

    Names only -- never values. Callers can report that a key was found
    without being able to leak what it was.
    """
    file = Path(path)
    if not file.exists():
        return []

    loaded: list[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip("'\"")
        if not name or not value:
            continue
        if name in os.environ:
            continue  # the real environment wins
        os.environ[name] = value
        loaded.append(name)
    return loaded


def key_status(*names: str) -> dict[str, bool]:
    """Whether each named key is set. Presence only, never the value."""
    return {name: bool(os.environ.get(name)) for name in names}
