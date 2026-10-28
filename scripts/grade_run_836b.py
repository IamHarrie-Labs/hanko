"""Grade run_836b976720f63dc0 (sealed 2026-10-23 18:05Z), two days after it fell due.

Window readings: the run's own decision-time sample, plus every scheduled-sweep
sample of the same DexScreener pools inside the 72h window. Independent voices:
re-read now from the run's original voices with the model reader, as the run did.

Run once, on 2026-10-28, as
    python scripts/grade_run_836b.py runs/run_836b976720f63dc0/review_samples.jsonl
with the reviews then copied to runs/run_836b976720f63dc0/reviews.jsonl. Kept as
the record of how that grade was made; running it again raises DuplicateReview.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from hanko.config import load_env
from hanko.decision import DecisionLedger, LlmInterpreter, Policy
from hanko.review import ReviewLedger, SampleTrail, review_decision
from hanko.snapshot import SnapshotStore
from hanko.sources import resolve
from hanko.sweep import fresh_observations, load_watchlist

load_env()
LIVE = Path(".hanko-live")
decisions = list(DecisionLedger(LIVE / "decisions.jsonl"))
decided = decisions[0].decided_at
due = decisions[0].review_at

trail_path = Path(sys.argv[1])
lines = (LIVE / "samples.jsonl").read_text(encoding="utf-8").splitlines()
for line in Path("live/samples.jsonl").read_text(encoding="utf-8").splitlines():
    at = datetime.fromisoformat(json.loads(line)["at"].replace("Z", "+00:00"))
    if decided <= at <= due:
        lines.append(line)
trail_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
trail = SampleTrail(trail_path)

entries = {e.token.upper(): e for e in load_watchlist("watchlist.json")}
store = SnapshotStore(LIVE / "snapshots")
interpreter = LlmInterpreter(model="grok-4.3")
reviews = ReviewLedger(LIVE / "reviews.jsonl")
now = datetime.now(timezone.utc)
for record in decisions:
    obs = fresh_observations(entries[record.subject.upper()], store, resolve=resolve, interpreter=interpreter,
                             policy=Policy(), as_of=now, trail=trail, since=record.decided_at)
    review = reviews.append(review_decision(record, obs))
    print(record.subject, record.verdict.value.upper(), "->", review.result.value.upper(),
          "| return", review.realised_return)
    for c in review.checks:
        print("   ", c.outcome.value.ljust(11), c.detail[:170])
print("interpreter", json.dumps(interpreter.stats.to_dict()))
