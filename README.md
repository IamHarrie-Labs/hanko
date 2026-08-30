# hanko

**An agent that files receipts.**

A 判子 is the seal a person stamps on a document to commit to it. The mark goes
on before the outcome is known and cannot be taken back — which is exactly what
this agent does with every decision it makes.

Twenty market voices go in. What comes out is a sized position, a receipt, and a
written commitment to what would prove it wrong — replayable, byte for byte,
from the exact data the agent saw.

Built for the RYO-CHAN platform and its seven read-only research tools.

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
hanko/provenance.py      canonical JSON, sha256 addressing, Status, Coverage
hanko/evidence.py        Evidence + Provenance — the source-agnostic unit
hanko/sources/base.py    the adapter contract
hanko/sources/xsearch.py X, via the xAI Responses API and its x_search tool
hanko/sources/rss.py     RSS/Atom — free, and the only source with trustworthy timestamps
hanko/sources/fixture.py local JSON — free development, and every failure mode in CI
hanko/snapshot/store.py  append-only content-addressed store, replay, integrity
hanko/review/outcome.py     grading a decision against its own commitment
hanko/review/reliability.py calibration, per-voice and per-rule track records
hanko/review/ledger.py      append-only reviews, one per decision
hanko/cli.py             collect / decide / review / scorecard / audit / verify
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
hanko collect x --subject voice_alpha --subject voice_beta
hanko collect rss --subject https://example.com/feed.xml
hanko ls
hanko replay snap_7723f3520b7dfa2efa6856e3
hanko verify
```

Offline, against a fixture:

```bash
hanko collect x --subject voice_alpha --fixture fixtures/x_three_voices.json
```

`XAI_API_KEY` must be set for live X collection. Without it the adapter records
a `FAILED` snapshot saying so, rather than throwing.

## Status

138 tests, all offline, ~5s. Covered at the evidence layer: canonical form and
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

At the MCP layer: the JSON-RPC handshake, session handling, SSE decoding, every
transport failure mode, and a test asserting that facts extracted from an MCP
payload are identical to facts extracted from a REST payload.

**Confirmed against the live API, 28 Aug 2026.** `x_search` does not return
structured post objects. It returns the model's *prose* rendering of the posts
plus an array of URL citations. Prose cannot be attributed to a specific post,
so the adapter requests a JSON schema and then verifies every returned post id
against the tool's own citations — cited posts are kept, uncited posts are
dropped. That check proves a post exists and that the tool saw it; it does not
prove the model transcribed the text or timestamp faithfully, so those fields
are flagged as model-transcribed on every item.

**Still unverified:** the RYO MCP endpoint URL is not yet in hand, so no live
tool call has run and the tool argument schemas remain a best guess. Run
`hanko tools` once the URL is known — it reports the real names and schemas and
diffs them against the seven published on the site.

## Decision Records

A record states, at the moment of the decision: what was concluded, on what
evidence, by what reasoning, what was missing, and **what would prove it wrong**.

```
hanko/decision/reading.py      interpretation, recorded once and frozen
hanko/decision/convergence.py  independence: is this many voices, or one echoed?
hanko/decision/quality.py      gaps, and the evidence-quality score that sets size
hanko/decision/policy.py       risk limits, hashed into every record
hanko/decision/engine.py       the verdict function -- pure by contract
hanko/decision/record.py       the record, and the commitment that names it
hanko/decision/ledger.py       append-only ledger, and the replay proof
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
hanko decide x --token TOKENA --subject voice_alpha --subject voice_beta --subject voice_gamma --market fixtures/market_tokena.json --as-of 2026-08-27T12:00:00Z --fixture fixtures/x_three_voices.json
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

`hanko audit` re-derives every recorded decision from stored bytes and insists it
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
hanko review --observations fixtures/observations_day3.json --now 2026-08-30T12:00:00Z
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
hanko scorecard
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
