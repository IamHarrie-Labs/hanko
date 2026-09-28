"""Decision workbench: change one input, watch the real engine's verdict move.

Runs the exact decide() the CLI and the sealing pipeline use, against one
captured decision baked into this function -- never live X or RYO calls,
so a public page can be explored at no cost and with no paid credential
behind it. Every experiment is computed fresh from the same pure inputs
and returned as a labelled hypothetical; nothing here is written to any
ledger, and the original decision (the one already printed throughout
this project's README) is never touched.

The baseline is fixtures/x_three_voices.json + fixtures/market_tokena.json,
embedded directly rather than read from a vendored fixtures/ directory --
one less deploy-time path to get wrong for two small, fixed JSON blobs.
"""

from __future__ import annotations

import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Vercel uploads only site/, so the vendored copy is how the function sees
# hanko/ at all there. Locally -- including under pytest -- the real
# package is already installed editable, and inserting a path that may not
# exist yet (before the first `python scripts/vendor_for_site.py`) would
# break every import; only prepend it when it is actually there.
_vendor = Path(__file__).resolve().parent / "_vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from hanko.decision import (  # noqa: E402
    DecisionInputs,
    KeywordInterpreter,
    MarketFacts,
    Policy,
    decide,
    read_all,
)
from hanko.snapshot import SnapshotStore  # noqa: E402
from hanko.sources import FixtureSource, Query  # noqa: E402
from hanko.provenance import to_iso  # noqa: E402

# Verbatim copies of fixtures/x_three_voices.json and
# fixtures/market_tokena.json -- the same bytes the CLI, the test suite,
# and the README's own printed examples all run against.
_EVIDENCE_FIXTURE = {
    "status": "ok",
    "coverage": "unknown",
    "error": None,
    "items": [
        {
            "external_id": "1900000000000000001",
            "author": "voice_alpha",
            "published_at": "2026-08-27T09:14:00Z",
            "text": "Accumulating $TOKENA here. Liquidity finally deep enough to size into.",
            "url": "https://x.com/voice_alpha/status/1900000000000000001",
            "extra": {"is_repost": False},
        },
        {
            "external_id": "1900000000000000002",
            "author": "voice_beta",
            "published_at": "2026-08-27T09:31:00Z",
            "text": "Agree with @voice_alpha on $TOKENA. Same thesis.",
            "url": "https://x.com/voice_beta/status/1900000000000000002",
            "extra": {"is_repost": True, "quoted_id": "1900000000000000001"},
        },
        {
            "external_id": "1900000000000000003",
            "author": "voice_gamma",
            "published_at": "2026-08-27T11:02:00Z",
            "text": "Independent look at $TOKENA: holder count up 12% w/w, no unlock until Q1.",
            "url": "https://x.com/voice_gamma/status/1900000000000000003",
            "extra": {"is_repost": False},
        },
    ],
}
_MARKET_FIXTURE = {
    "subject": "TOKENA",
    "price_usd": 1.25,
    "volume_24h_usd": 4200000.0,
    "liquidity_usd": 900000.0,
    "safety_score": 0.82,
    "snapshot_id": "snap_market_demo",
}
TOKEN = "TOKENA"
SUBJECTS = ("voice_alpha", "voice_beta", "voice_gamma")
AS_OF = "2026-08-27T12:00:00Z"
MARKET_FIELDS = ("price_usd", "volume_24h_usd", "liquidity_usd", "safety_score")


def _load_baseline_evidence():
    """Collect + replay the embedded fixture through a real, throwaway store.

    Going through SnapshotStore rather than calling FixtureSource.parse()
    directly is what makes this the same code path `hanko decide` runs --
    the resulting evidence_ids and the baseline decision_id are identical
    to the ones already printed in README.md, not a lookalike reconstructed
    by hand.
    """
    from datetime import datetime, timezone

    tmp = Path(tempfile.mkdtemp(prefix="hanko_workbench_"))
    fixture_path = tmp / "x_three_voices.json"
    fixture_path.write_text(json.dumps(_EVIDENCE_FIXTURE), encoding="utf-8")

    store = SnapshotStore(tmp / "snapshots")
    source = FixtureSource(fixture_path, source_id="fixture:x")
    as_of = datetime.fromisoformat(AS_OF.replace("Z", "+00:00"))
    snap = store.collect(source, Query(subjects=SUBJECTS), requested_at=as_of)
    evidence = store.replay(snap.snapshot_id, source)
    return evidence, (snap.snapshot_id,), as_of


def _make_market(missing: set[str]) -> MarketFacts:
    base = dict(_MARKET_FIXTURE)
    for field in missing:
        base[field] = None
    return MarketFacts.from_dict(base)


def _run(evidence, snapshot_ids, as_of, market: MarketFacts, policy: Policy):
    interpreter = KeywordInterpreter()
    readings = read_all(interpreter, list(evidence))
    return decide(
        DecisionInputs(
            subject=TOKEN,
            evidence=tuple(evidence),
            readings=tuple(readings),
            market=market,
            as_of=as_of,
            snapshot_ids=snapshot_ids,
            sources_requested=len(SUBJECTS),
            interpreter_id=interpreter.interpreter_id,
            interpreter_version=interpreter.interpreter_version,
            notes={"sources_requested": len(SUBJECTS)},
        ),
        policy,
    )


def _evidence_view(evidence, record) -> list[dict]:
    """Every post, annotated with why it did or didn't count as independent."""
    echoes = {e.evidence_id: e for e in record.convergence.echoes}
    out = []
    for item in evidence:
        echo = echoes.get(item.evidence_id)
        out.append(
            {
                "evidence_id": item.evidence_id,
                "author": item.author,
                "text": item.text,
                "url": item.url,
                "published_at": to_iso(item.published_at) if item.published_at else None,
                "is_repost": bool(item.extra.get("is_repost")),
                "is_echo": echo is not None,
                "echo_reason": echo.reason if echo else None,
            }
        )
    return out


def _rule_map(record) -> dict[str, dict]:
    return {r.rule_id: {"outcome": r.outcome.value, "detail": r.detail} for r in record.rules}


def _diff(baseline, experiment) -> dict:
    base_rules, exp_rules = _rule_map(baseline), _rule_map(experiment)
    changed = []
    for rule_id in sorted(set(base_rules) | set(exp_rules)):
        b, e = base_rules.get(rule_id), exp_rules.get(rule_id)
        if b != e:
            changed.append({"rule_id": rule_id, "before": b, "after": e})
    return {
        "verdict_changed": baseline.verdict != experiment.verdict,
        "verdict_before": baseline.verdict.value,
        "verdict_after": experiment.verdict.value,
        "size_fraction_before": round(baseline.size_fraction, 6),
        "size_fraction_after": round(experiment.size_fraction, 6),
        "confidence_before": round(baseline.confidence, 6),
        "confidence_after": round(experiment.confidence, 6),
        "independent_voices_before": baseline.convergence.independent_voices,
        "independent_voices_after": experiment.convergence.independent_voices,
        "rule_changes": changed,
    }


def _record_view(record) -> dict:
    return {
        "decision_id": record.decision_id,
        "verdict": record.verdict.value,
        "confidence": round(record.confidence, 4),
        "size_fraction": round(record.size_fraction, 6),
        "quality": record.quality.to_dict(),
        "convergence": record.convergence.to_dict(),
        "rules": [r.to_dict() for r in record.rules],
        "gaps": [g.to_dict() for g in record.gaps],
        "falsifiers": [f.to_dict() for f in record.falsifiers],
        "explain": record.explain(),
    }


def _run_workbench(exclude: set[str], missing: set[str], policy_overrides: dict) -> dict:
    evidence, snapshot_ids, as_of = _load_baseline_evidence()
    baseline_policy = Policy()
    baseline = _run(evidence, snapshot_ids, as_of, _make_market(set()), baseline_policy)

    bad_exclude = exclude - set(SUBJECTS)
    bad_fields = missing - set(MARKET_FIELDS)
    if bad_exclude or bad_fields:
        return {
            "error": "unknown "
            + (("author(s) " + ", ".join(sorted(bad_exclude))) if bad_exclude else "")
            + (("field(s) " + ", ".join(sorted(bad_fields))) if bad_fields else ""),
            "allowed_authors": list(SUBJECTS),
            "allowed_fields": list(MARKET_FIELDS),
        }

    filtered_evidence = [e for e in evidence if e.author not in exclude]
    policy_kwargs = {}
    if "min_independent_voices" in policy_overrides:
        policy_kwargs["min_independent_voices"] = int(policy_overrides["min_independent_voices"])
    if "echo_similarity" in policy_overrides:
        policy_kwargs["echo_similarity"] = max(0.0, min(1.0, float(policy_overrides["echo_similarity"])))
    if "min_evidence_quality" in policy_overrides:
        policy_kwargs["min_evidence_quality"] = max(0.0, min(1.0, float(policy_overrides["min_evidence_quality"])))
    experiment_policy = Policy(**policy_kwargs)

    experiment = _run(
        filtered_evidence, snapshot_ids, as_of, _make_market(missing), experiment_policy
    )

    return {
        "token": TOKEN,
        "baseline": {**_record_view(baseline), "evidence": _evidence_view(evidence, baseline)},
        "experiment": {
            **_record_view(experiment),
            "evidence": _evidence_view(filtered_evidence, experiment),
            "excluded_authors": sorted(exclude),
            "missing_fields": sorted(missing),
            "policy_overrides": policy_kwargs,
        },
        "diff": _diff(baseline, experiment),
    }


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query)
        exclude = {a for a in query.get("exclude", [""])[0].split(",") if a}
        missing = {f for f in query.get("missing", [""])[0].split(",") if f}
        overrides = {}
        for key in ("min_independent_voices", "echo_similarity", "min_evidence_quality"):
            if key in query:
                overrides[key] = query[key][0]

        try:
            result = _run_workbench(exclude, missing, overrides)
        except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
            self._send_json(502, {"error": type(exc).__name__ + ": " + str(exc)})
            return
        status = 400 if "error" in result and "baseline" not in result else 200
        self._send_json(status, result)
