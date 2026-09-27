# Decisions

Engineering decisions and the bugs that shaped them, in the order they happened.
Each one changed a real number or a real guarantee, not a preference.

## D-01: One boundary, drawn before anything else

`fetch()` touches the network, is allowed to fail, and is never deterministic.
`parse()` touches nothing, and is a pure function of its payload. The decision
engine only ever sees the output of `parse()`.

Every other decision in this document is that boundary being defended somewhere
it would otherwise have leaked: a model call inside `parse()`, a clock read
inside `decide()`, a re-fetch inside replay. Each of those would have been
convenient once and would have cost the one property the whole project rests
on: that a past decision can be re-derived from stored bytes and must reach the
same verdict.

## D-02: Three verdicts, not two

`ENTER`, `PASS` (the evidence was adequate and argued against entry), and
`ABSTAIN` (the evidence was not adequate to argue either way). Collapsing the
last two into a single "did not enter" would let the agent claim a market view
it never actually held, and would make `PASS` and `ABSTAIN` indistinguishable
in the scorecard even though they earn opposite credit for caution.

## D-03: Evidence quality as a geometric mean, not an average

Four components (completeness, freshness, corroboration, independence)
combine as a weighted geometric mean rather than an arithmetic one. A component
at zero takes the whole score to zero. An arithmetic mean lets three strong
components hide one absent one; a geometric mean does not, because that is
exactly the failure mode a missing safety check or a stale post represents.

## D-04: Snapshot ids need a sequence number, not just a timestamp

Windows' clock resolution is coarse enough that two snapshots captured back to
back can carry the identical timestamp, which produced duplicate snapshot ids
during early development. Fixed by hashing the store's own append-only
position into the id alongside the timestamp, so two captures are never
identical even when the clock says they were.

## D-05: `exit_liquidity` reports null, never zero, for a missing input

If pool liquidity is unavailable, the slippage fields are `null` and the
verdict is `unknown`, never `0`. A zero here would read as "free to exit,"
which is the single most dangerous fabrication this particular tool could
make. This rule turned out to matter immediately: RYO's `deep_analysis` has
never once returned pool depth for any token checked live, so every real call
this tool has made has exercised exactly this path.

## D-06: The real RYO catalog is six tools, not seven

The first build was written against the hackathon's own public tool list:
seven tools, including a numeric `check_safety` score. A live call to
`tools/list` against the real MCP endpoint told a different story:
`check_safety` and `supported_tokens` are not on the authenticated catalog,
`monitor_market_sentiment_shift` is and had never been guessed at, argument
keys are `symbol` rather than `token`, and there is no numeric safety score
anywhere in the six real tools. `client.py`, `mcp.py`, the tests and the
README were rewritten the same day to match the live behaviour rather than the
published description. `safety_score` on `MarketFacts` now stays `None` on
every decision, honestly, instead of sometimes.

## D-07: `hanko audit` crashing on any fixture-captured decision

A routine run of `hanko audit` (the command that re-derives every stored
decision and insists it reproduces) crashed with `PayloadShapeError: no
message item in the response output`.

The cause was a labelling bug: `FixtureSource(args.fixture, source_id=args.source)`
tagged a decision built from local test data with the *live* source's own id
(`"x"`) instead of anything marking it as a fixture. On replay,
`resolve("x")` did exactly what it is supposed to and returned the real X
adapter, which was then handed fixture-shaped bytes it was never built to
read.

Every existing replay test had missed this, because each one supplied its own
hand-rolled resolver that returned a fixture unconditionally, and none of them
went through the actual lookup `hanko audit` uses. The fix tags fixture
captures `fixture:<name>`, matching the `ryomcp:` / `ryo:` prefix convention
already used for the RYO tool sources, so the real resolver can tell a
fixture apart from a live capture on its own. A new test goes through that
real resolver deliberately, and was checked both ways: confirmed to fail
without the fix, confirmed to pass with it.

## D-08: The symmetry rule had no tied state

`evidence leans bullish` / `evidence leans bearish` was computed as a
two-branch ternary on `bull_weight > bear_weight`. When both were exactly
zero (the all-neutral case, no bullish or bearish language at all), the
ternary's `else` branch printed "leans bearish" for evidence that leaned
nowhere. Fixed by giving the rule a third state, "evidence is directionally
neutral," so a real zero-vs-zero reading is reported as what it is instead of
an unearned direction.

## D-09: A missing market field was being reported twice

`sweep._collect_facts` raised a `MARKET_FIELD_MISSING` gap for every field
`extract_market_facts` reported absent, and the decision engine's own
`_collect_gaps` independently derived the same gaps from the same
`market.missing` a few lines later. Every genuinely missing field showed up
twice in a decision's gap list. Fixed by making the engine the single owner of
market-field gaps; `sweep` now only raises `SOURCE_FAILED` for a tool that
never answered at all, which is the one thing only it can see.

## D-10: Price formatting broke across nine orders of magnitude

`exit_liquidity`'s live report rounds prices to whole dollars, which is
correct for BTC and silently prints a real BONK quote of $0.0000034 as $0,
a measured number destroyed by its own formatting. Every token checked live
runs through the same formatter, from a nine-cent memecoin to an
$80,000 BTC quote, so the fix scales precision to the value instead of using
one fixed number of decimal places for every token.

## D-11: `0.0h` is not the same as "no time estimate"

A deep pool and a modest position size give a real, correct answer of a few
seconds to exit, which the CLI was rounding to `0.0h` and the web widget was
about to print as an unqualified zero, indistinguishable from a missing
value. Both now scale the unit to the duration: minutes, "under a minute," or
days, so a genuinely fast exit reads as fast rather than as absent.

## D-12: D-04's fix only half worked

A test failed intermittently, not on every run: `test_identical_payloads_are_stored_once`
occasionally produced two snapshots with the same id from two back-to-back
`collect()` calls. D-04's fix was supposed to make exactly that impossible.

The cause: `SnapshotStore._sequence` is set once in `__init__`, from the
index file's line count, and was never incremented after a successful
write. Every `put()` inside one store instance's lifetime reused the same
sequence number, so it only disambiguated two writes across separate store
instances, never two writes through the same one. Two collects landing in
the same clock tick, with the sequence also identical, produced the exact
collision D-04 documented as solved.

Fixed by incrementing `_sequence` after each write actually succeeds, so a
crash mid-write cannot skip a number ahead of what is genuinely recorded.
The regression test that had only caught this by luck was replaced with one
that forces an identical `requested_at` on both collects, removing the
clock as a disambiguator entirely and isolating the sequence number as the
only thing left that can tell two snapshots apart, confirmed to fail
without the fix and pass with it.

## D-13: A falsifier said "within 72h" and only checked the last tick

Every receipt prints its falsifiers as `price_usd < X within 72.0h`. The
grader did not check "within." `review_decision()` compared one reading,
taken at review time, against the threshold. A price that fell through the
15%-drawdown line at hour 30 and recovered by hour 72 would be graded HELD,
even though the falsifier's own words promised otherwise -- the exact
scenario a pre-registered falsifier exists to catch, missed by the one
component meant to enforce it.

Not every falsifier has this problem. `independent_voices` asks whether the
convergence an entry rested on still holds -- a question about now, correctly
answered by the latest reading alone. Only `price_usd` and `liquidity_usd`
name a condition that, once true at any moment, makes the thesis wrong for
good even if the metric later recovers.

Fixed with two changes. First, every `Falsifier` now states its own window
explicitly: `AT_REVIEW_TIME` for a state check, `ANY_POINT_IN_WINDOW` for a
thesis-invalidating breach. No default -- every falsifier the engine writes
picks one, on purpose, rather than inheriting a behaviour nobody chose.
Second, `Observations` became a series of samples instead of one reading, so
an `ANY_POINT_IN_WINDOW` falsifier can be checked against every sample that
reports its metric, not just the last one. A single sample still works --
it is graded as the one instant it is, and the review's own wording says so
("1 sample ... no intermediate readings") rather than implying coverage of
a window it never actually watched.

`hanko sweep --samples` is what actually fills that series in practice: it
appends one market reading per watched token every pass, reusing facts the
sweep already fetched, so a decision graded weeks from now has real
intra-window history instead of one more single point pretending to be the
whole window. Omitting `--samples` keeps the narrower, honest, pre-D-13
behaviour -- one reading, and only an `AT_REVIEW_TIME` falsifier can be
fully answered by it.

Because the falsifier's shape changed, `engine_version` moved to `1.1.0`
and every decision's `commitment_digest` -- and therefore its `decision_id`
-- changed with it. Nothing published under the old shape existed yet, so
this was the last free moment to fix it before a sealed receipt would have
had to carry a promise the grader could not keep.

A regression test forces a breach at hour 30 and a recovery by hour 72
across two samples, confirmed to report HELD without the window-aware
check and FALSIFIED with it. A second test checks the boundary the other
way: `independent_voices`, an `AT_REVIEW_TIME` falsifier, is fed the same
kind of mid-window dip and must not fire on it -- only the reading at
review time is its business, or the fix would just be moving which
falsifiers lie about their own window.
