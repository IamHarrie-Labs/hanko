# Limitations

What this project has not shown, stated as plainly as what it has. A project
about not overclaiming should not overclaim about itself either.

**No live sweep has run long enough to produce a calibration curve from real
outcomes.** The scorecard's Brier score and calibration buckets are proven
against synthetic review histories in tests, not against a real track record
accumulated over time. That requires decisions made, then genuinely waited
out, which this build's timeline has not allowed for.

**No live `ENTER` has been produced.** Real runs against real X posts and real
RYO market data have reached `PASS` and `ABSTAIN` honestly (the evidence
gate and the independence check both hold under real conditions), but an
`ENTER` needs two independent voices actually converging on one ticker inside
a single review window, and no observed window has supplied that yet. The
fixture-based `ENTER` shown on the homepage's hero receipt is real engine
output, clearly labelled as running on fixed sample inputs, not live data.

**`exit_liquidity` has never priced a real pool.** RYO's `deep_analysis` has
returned `null` for pool liquidity on every live call made, for every token
checked, so the tool's headline cost-of-exit figure has only ever answered
`unknown` against live data. The constant-product model itself is proven
against closed-form values in tests; it has not yet been exercised against a
real, non-null liquidity figure, because the platform has not yet supplied
one.

**X evidence is demonstrated against fixtures by default, not live, for cost
reasons.** Each live `x_search` call costs roughly $0.012. The transport
itself (the JSON-schema request, the citation-verification step, SSE
decoding, session handling) is live-tested and confirmed working against the
real xAI API. Routine demonstration and CI both run against fixtures so
development and review cost nothing and hit no rate limit.

**The public `/try` page only exercises RYO facts, not X evidence.** RYO's own
calls are free against the hackathon credential, which is what makes exposing
them on an unauthenticated public page acceptable at all. `x_search` calls
cost real money per request; exposing that on a public page would let anyone
on the internet spend against this project's own paid credential with no
practical ceiling. The full evidence-plus-facts pipeline exists and is
tested, but stays a command you run yourself, under your own credentials, not
a button on a public website.

**The evidence interpreter is rule-based, not a model.** `KeywordInterpreter`
matches cashtags and a fixed table of bullish/bearish/urgency/hedging words. It
is deliberately unsophisticated: its value is that it is pure and free, so the
whole pipeline can be tested and the replay guarantee proven without a model
in the loop. An LLM interpreter is a drop-in replacement behind the same
`Interpreter` protocol, and its readings would be recorded and replayed
exactly the same way, but swapping it in was out of scope for this build, and would
trade determinism at the interpretation step for whatever the model actually
returns.

**Reported evidence quality has an unmeasured floor.** The geometric-mean
score components (completeness, freshness, corroboration, independence) are
each computed from what the sources actually returned. None of them measure
whether the *content* of a post is true, only whether it exists, is recent,
is corroborated and is independent. A confidently wrong but well-corroborated
claim scores the same as a confidently right one; nothing in this project
checks a post's claims against reality beyond what the falsifier check does
after the fact, at review time.
