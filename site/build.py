"""Refresh the site's numbers from the repository they describe.

The receipt on the page is labelled LIVE OUTPUT. This is what makes that
label true: the trail is produced by actually running the agent, and the
counters are read from the test suite and from git. A page about not
overclaiming should not hand-maintain its own statistics.

    python site/build.py            # rewrite site/index.html in place
    python site/build.py --check    # exit 1 if it is stale, change nothing

`--check` is the CI form: it fails the build when the site has drifted
from the code rather than letting a stale number ship.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = Path(__file__).resolve().parent
INDEX = SITE_DIR / "index.html"
# Every page that carries the live stat spans or the GitHub link. The
# trail substitution is index-only in effect: docs.html has no
# <pre id="trail"> for the regex to match, so it is a safe no-op there.
PAGES = (INDEX, SITE_DIR / "docs.html")

# Fixed inputs, so the published trail is reproducible rather than
# whatever the market happened to look like when the site was built.
DECIDE = [
    sys.executable, "-m", "hanko.cli", "decide", "x",
    "--token", "TOKENA",
    "--subject", "voice_alpha", "--subject", "voice_beta", "--subject", "voice_gamma",
    "--market", "fixtures/market_tokena.json",
    "--as-of", "2026-08-27T12:00:00Z",
    "--fixture", "fixtures/x_three_voices.json",
]

WRAP_AT = 60


def run(args: list[str], cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            "command failed: " + " ".join(args) + "\n" + result.stdout + result.stderr
        )
    return result.stdout


def wrap_trail(text: str) -> str:
    """Wrap long lines with a hanging indent aligned under the content.

    The receipt card is narrower than the agent's terminal output. Letting
    `pre-wrap` break the lines works but loses the alignment that makes a
    trail readable, so continuation lines are indented to sit under the
    text they continue.
    """
    out: list[str] = []
    for line in text.splitlines():
        if len(line) <= WRAP_AT:
            out.append(line)
            continue

        stripped = line.lstrip()
        lead = len(line) - len(stripped)
        # Continuations align past the marker ("+ ", "! ", "~ ") where there
        # is one, so the sigil column stays clean down the left edge.
        marker = 2 if stripped[:2] in ("+ ", "! ", "~ ", "x ", "? ", ". ") else 0

        out.extend(
            textwrap.wrap(
                stripped,
                width=WRAP_AT,
                initial_indent=" " * lead,
                subsequent_indent=" " * (lead + marker),
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [line]
        )
    return "\n".join(out)


def decision_trail() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        # --root is a global flag, so it goes before the subcommand. The
        # snapshot store and ledger are thrown away: the site publishes the
        # trail, not the capture.
        cmd = DECIDE[:3] + ["--root", tmp] + DECIDE[3:]
        raw = run(cmd + ["--ledger", str(Path(tmp) / "d.jsonl")])
    lines = [
        line.rstrip()
        for line in raw.splitlines()
        if not line.startswith("  recorded in ")
    ]
    while lines and not lines[-1].strip():
        lines.pop()
    return wrap_trail("\n".join(lines))


def test_count() -> str:
    out = run([sys.executable, "-m", "pytest", "--collect-only", "-q"])
    match = re.search(r"(\d+) tests? collected", out)
    if not match:
        raise SystemExit("could not read a test count from pytest")
    return match.group(1)


def line_count() -> str:
    total = 0
    for path in list((ROOT / "hanko").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        total += len(path.read_text(encoding="utf-8").splitlines())
    return format(total, ",")


def commit_count() -> str:
    return run(["git", "rev-list", "--count", "HEAD"]).strip()


def repo_url() -> str | None:
    try:
        url = run(["git", "remote", "get-url", "origin"]).strip()
    except SystemExit:
        return None
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url.removesuffix(".git") or None


def apply(source: str, *, trail: str, stats: dict[str, str], repo: str | None) -> str:
    source = re.sub(
        r'(<pre id="trail" data-trail=")(.*?)(">)',
        lambda m: m.group(1) + html.escape(trail, quote=True) + m.group(3),
        source,
        flags=re.S,
    )
    for key, value in stats.items():
        source = re.sub(
            r'(data-stat="' + key + r'"[^>]*>)[^<]*(</)',
            lambda m: m.group(1) + value + m.group(2),
            source,
        )
    if repo:
        source = re.sub(r'href="[^"]*" data-repo', 'href="' + repo + '" data-repo', source)
        source = re.sub(r'data-repo href="[^"]*"', 'data-repo href="' + repo + '"', source)
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the site is stale")
    args = parser.parse_args()

    if shutil.which("git") is None:
        raise SystemExit("git is required to read the commit count")

    # Computed once and applied to every page, so the test count on the
    # docs page can never read differently from the one on the homepage.
    trail = decision_trail()
    stats = {
        "tests": test_count(),
        "lines": line_count(),
        "commits": commit_count(),
    }
    repo = repo_url()

    stale = []
    for page in PAGES:
        if not page.exists():
            continue
        current = page.read_text(encoding="utf-8")
        updated = apply(current, trail=trail, stats=stats, repo=repo)
        if updated == current:
            continue
        stale.append((page, updated))

    if not stale:
        print("site is current")
        return 0
    if args.check:
        for page, _ in stale:
            print("stale: " + str(page.relative_to(ROOT)), file=sys.stderr)
        print("run: python site/build.py", file=sys.stderr)
        return 1

    for page, updated in stale:
        page.write_text(updated, encoding="utf-8")
        print("rewrote " + str(page.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
