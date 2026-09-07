"""Copy hanko/ into site/api/_vendor/ so it deploys alongside the site.

The Vercel project's root is site/, so a Python function under site/api/
has no access to the hanko/ package one level up unless it travels with
the upload. Run this before every `vercel deploy` that touches the site's
"test it live" endpoint. Not committed to git -- hanko/ at the repo root
stays the one source of truth; this is a build artifact.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "hanko"
DEST = ROOT / "site" / "api" / "_vendor" / "hanko"


def _ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n == "__pycache__"]


def _sources(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def stale() -> list[str]:
    """Vendored files that differ from the package, or are missing."""
    if not DEST.exists():
        return ["<not vendored at all>"]
    src, dest = _sources(SRC), _sources(DEST)
    return sorted(
        name for name in set(src) | set(dest) if src.get(name) != dest.get(name)
    )


def main() -> None:
    # --check is the pre-deploy guard. Deploying a stale copy would put
    # code on the live demo that differs from the code in the repo, which
    # on this project of all projects is not a cosmetic difference.
    if "--check" in sys.argv:
        drift = stale()
        if drift:
            for name in drift[:10]:
                print("stale:", name)
            print("run: python scripts/vendor_for_site.py")
            raise SystemExit(1)
        print("vendored copy matches hanko/")
        return

    if DEST.parent.exists():
        shutil.rmtree(DEST.parent)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, DEST, ignore=_ignore)
    print("vendored", SRC, "->", DEST)


if __name__ == "__main__":
    main()
