# ryo-brain — evidence layer

The ingestion and provenance foundation for a RYO-CHAN agent. Everything the
agent later reasons over enters through here, and everything it claims later
traces back through here to bytes that were actually received.

## The one rule

```
fetch()  touches the network, is allowed to fail, and is never deterministic
parse()  touches nothing, and is a pure function of its payload
```

The agent only ever sees the output of `parse()`. Because `parse()` is pure and
payloads are content-addressed, any past decision can be re-derived from stored
bytes and must reach the same verdict. Put a network call inside `parse()` and
the reasoning trail stops being reproducible — which is the property the whole
submission rests on.

## Layout

```
ryo/provenance.py      canonical JSON, sha256 addressing, Status, Coverage
ryo/evidence.py        Evidence + Provenance — the source-agnostic unit
ryo/sources/base.py    the adapter contract
ryo/sources/xsearch.py X, via the xAI Responses API and its x_search tool
ryo/sources/rss.py     RSS/Atom — free, and the only source with trustworthy timestamps
ryo/sources/fixture.py local JSON — free development, and every failure mode in CI
ryo/snapshot/store.py  append-only content-addressed store, replay, integrity
ryo/review/outcome.py     grading a decision against its own commitment
ryo/review/reliability.py calibration, per-voice and per-rule track records
ryo/review/ledger.py      append-only reviews, one per decision
ryo/cli.py             collect / decide / review / scorecard / audit / verify
```

## Why it is built this way

**Sources are interchangeable.** The agent never learns where a piece of
evidence came from. Swapping X for Telegram, or Grok for a direct API, changes
one adapter and nothing downstream. If `x_search` is deprecated or priced out on
day 9, nothing else moves.

**Failure is data, not an exception.** A source that was asked and did not
answer produces a `FAILED` snapshot with the reason attached. An adapter that
raises produces one too. Silence is the single outcome this store cannot
represent — which is what lets position sizing respond honestly to missing
evidence instead of quietly proceeding as if the data were there.

**Three different kinds of nothing stay distinct.** `FAILED` (the source did not
answer), `OK` with zero items (nobody posted), and `PayloadShapeError` (bytes
arrived that we cannot read) are separate facts. Collapsing them would let a
schema change look like a quiet market.

**Coverage is never overclaimed.** `x_search` is a search tool, not a timeline
feed, so its coverage is `UNKNOWN` by construction. Claiming `COMPLETE` is
precisely the lie that would inflate a convergence count across KOLs.

**Collect once, develop free.** Real snapshots are captured once and everything
afterwards runs against stored bytes. Development and CI cost nothing and hit no
rate limit. At an hourly sweep over 20 handles, live collection runs about
$0.005/call — roughly $25–35 for the whole build.

## Use

```bash
pip install -e ".[dev]"
pytest
```

```bash
ryo collect x --subject voice_alpha --subject voice_beta
ryo collect rss --subject https://example.com/feed.xml
ryo ls
ryo replay snap_7723f3520b7dfa2efa6856e3
ryo verify
```

Offline, against a fixture:

```bash
ryo collect x --subject voice_alpha --fixture fixtures/x_three_voices.json
```

`XAI_API_KEY` must be set for live X collection. Without it the adapter records
a `FAILED` snapshot saying so, rather than throwing.

## Status

82 tests, all offline, ~2.5s. Covered at the evidence layer: canonical form and
address stability, payload deduplication, tamper detection, adapter-version
mismatch on replay, replay determinism, evidence identity pinned to bytes and
position, and each failure mode (rate limit, partial window, empty result,
raising adapter, malformed feed, unreadable payload). At the decision layer:
echo demotion, PASS vs ABSTAIN separation, mechanical size reduction under
missing safety data / a failed source / stale evidence, falsifier generation for
both entries and refusals, ledger tamper detection, and end-to-end reproduction
of a stored decision from stored bytes. At the review layer: falsifier checking,
profit not rescuing a falsified thesis, uncheckable metrics staying unresolved,
inconclusive reviews excluded from every rate, echoes earning neither credit nor
blame, calibration, and the refusal to re-review a decision.

**Unverified:** the exact shape of `x_search` tool results. `_extract_posts`
walks the payload structurally rather than assuming a path, and raises
`PayloadShapeError` when nothing post-shaped is found. Confirm the real shape on
the first live call, tighten the extractor, and bump `adapter_version` — old
snapshots keep their original bytes and can be re-parsed rather than re-fetched.

## Decision Records

A record states, at the moment of the decision: what was concluded, on what
evidence, by what reasoning, what was missing, and **what would prove it wrong**.

```
ryo/decision/reading.py      interpretation, recorded once and frozen
ryo/decision/convergence.py  independence: is this many voices, or one echoed?
ryo/decision/quality.py      gaps, and the evidence-quality score that sets size
ryo/decision/policy.py       risk limits, hashed into every record
ryo/decision/engine.py       the verdict function -- pure by contract
ryo/decision/record.py       the record, and the commitment that names it
ryo/decision/ledger.py       append-only ledger, and the replay proof
```

**The engine is pure.** `decide()` reads its arguments and nothing else: no
clock, no network, no model call, no randomness. Interpretation is the one
subjective step, so it happens upstream and is frozen into the record. Put an
LLM in the decision path and replay proves nothing.

**Three verdicts, not two.** `ENTER`, `PASS` (the evidence was adequate and
argued against it), and `ABSTAIN` (the evidence was not adequate to argue either
way). Collapsing the last two would let the agent claim a market view it never
had.

**Missing data shrinks the position, mechanically.** No rule says "if safety is
unavailable then halve". A gap lowers completeness, completeness lowers evidence
quality, and quality sets size. The four quality components combine as a
weighted *geometric* mean, so a component at zero takes the whole score to zero
— enthusiasm cannot average away an absent safety check.

**Agreement is checked for independence.** Three accounts quoting one thesis is
one observation in disguise, and counting it as three is the easiest way for a
multi-KOL agent to be confidently wrong. Every echo is recorded with the post it
repeats and the reason it was demoted.

**Every decision pre-registers its own falsification.** Falsifiers are written
before the outcome is known, evaluate mechanically, and are hashed into the
`decision_id`. Move a threshold, a size, or a review date after the fact and you
get a different id — a new decision, not an edited one. Refusals commit too: a
`PASS` records what would flip it.

### Seeing it

```bash
ryo decide x --token TOKENA --subject voice_alpha --subject voice_beta --subject voice_gamma --market fixtures/market_tokena.json --as-of 2026-08-27T12:00:00Z --fixture fixtures/x_three_voices.json
```

```
ENTER TOKENA  size 3.28%  confidence 0.66
  dec_0074a4b93cc07a2a0d799a9b
  evidence quality 0.82  (completeness 1.0, freshness 0.75, corroboration 1.0, independence 0.67)
  + independent_voices: 2 independent voice(s): voice_alpha, voice_gamma
  + safety: safety score 0.82
  ~ echo voice_beta: marked as a repost or quote by the source
  ! wrong if price_usd < 1.0625 within 72.0h (thesis fails if price falls 15% from entry)
  ! wrong if independent_voices < 2.0 within 72.0h (entry rested on convergence that no longer holds)
  review at 2026-08-30T12:00:00Z

  replayed from stored bytes: same decision id
```

Three authors mentioned the token; two of them were independent. Swap in the
market fixture with no safety score and the same evidence sizes at 3.08%
instead of 3.28% — nothing in the rules changed, only what was known.

`ryo audit` re-derives every recorded decision from stored bytes and insists it
reproduces. That is the CI gate that turns "preserves a repeatable reasoning
trail" from a README claim into a failing build.

## The review loop

At `review_at`, each falsifier is evaluated against observed facts and the
decision is graded **against what it committed to** — not against whether it
happened to make money.

Those come apart more often than is comfortable. An entry can be profitable and
still falsified: the price rose while the liquidity that justified the size
drained away, meaning the reasoning was wrong and the outcome was luck. Both
facts are recorded and reported separately. Grading on profit alone is how an
agent learns to repeat lucky mistakes.

**The third outcome carries the weight.** When the metric a falsifier names is
unavailable at review time, the check is `UNCHECKABLE` — never quietly counted
as passing. A decision that could not be checked is not a decision that was
right. Inconclusive reviews are excluded from every rate and reported as their
own number, because an agent that silently drops what it could not verify is
grading itself on a sample it chose after the fact.

**Refusals are graded too.** A `PASS` commits to what would have flipped it, so
an agent that only marks the trades it took never learns what its caution cost.

**One review per decision, enforced.** Re-reviewing until the answer improves is
the exact failure pre-registration exists to prevent, so the ledger refuses a
second review rather than keeping the latest.

```bash
ryo review --observations fixtures/observations_day3.json --now 2026-08-30T12:00:00Z
```

```
FALSIFIED  TOKENA  (enter at confidence 0.66)
  dec_dc6b3d83c289b886b2097e39 -> rev_8a7fe39dcabbfbf95ddff178
  x price_usd observed at 1.02; committed to being wrong if < 1.0625 -- thesis fails if price falls 15% from entry
  + liquidity_usd observed at 880000.0; holds against < 630000.0
  + independent_voices observed at 2.0; holds against < 2.0
  realised return -18.4%  (recorded, not used to grade)
```

### The scorecard

```bash
ryo scorecard
```

```
reviewed 2   scored 2   unverifiable 0
held 1   falsified 1   hit rate 50.0%   brier 0.2461

calibration        said     actual    n
  0.6-0.8         0.7       50.0%    2

voices
  voice_gamma               0.0%   1 scored
  voice_alpha              50.0%   2 scored

rules satisfied on decisions that later
  independent_voices       0.0% held
  conviction              50.0% held
```

Said 0.7, was right 50% of the time — the agent is overconfident, and says so.

Per-voice reliability is **earned from the agent's own audited history**, not
asserted from follower counts, and echoes earn neither credit nor blame. A voice
with no scored decisions gets `None`, not 0% — reporting it as zero would defame
it, reporting it as 100% would promote it. Per-rule reliability answers the
uncomfortable question: a rule that is always satisfied on losers is not a
filter, it is decoration.

## Next

Wire `audit` and `scorecard` into CI, and feed per-voice reliability back into
evidence weighting so the agent's own track record starts shaping what it
believes.
