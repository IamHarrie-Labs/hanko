# Limitations

What this project has not shown, stated as plainly as what it has. A project
about not overclaiming should not overclaim about itself either.

**RYO's market data has failed on every live call made with this key since
2026-09-28.** `analyze_token`, `deep_analysis` and `compare_tokens` return
`400 VALIDATION_FAILED` ("couldn't analyze BTC right now") for every token,
while health, the catalog and quota all answer normally. A support ticket
with trace ids is open. Until it is resolved, live decisions take price,
24h volume and pool depth from DexScreener's canonical pools, labelled as
such and on-chain only. RYO's safety and technical fields (safety score,
ATR) stay missing. Each missing field is a recorded gap that lowers
evidence quality and so position size; none of them is filled with a guess.

**One live `ENTER`, not a track record.** The first live `ENTER` (BTC,
`runs/run_836b976720f63dc0.json`, 2026-10-23) was small (1.64%, confidence
0.33) because evidence quality only just cleared the floor. Its falsifiers
come due on 2026-10-26. One sealed decision shows the lifecycle works. It is
not evidence that the agent is right, and the scorecard's calibration buckets
are still proven against synthetic review histories in tests, not a real
series.

**The first two sealed runs can no longer be replayed** (D-17). Their
manifests and OpenTimestamps proofs still prove what was committed and when.
The snapshot bytes their decisions cite were in a local store that was
deleted during test cleanup. Every run since carries a replay bundle.

**`exit_liquidity` quotes Solana tokens only.** Jupiter supplies an
executable quote for SOL, BONK, JUP and WIF. ETH and BTC are measured
through WETH and WBTC on Ethereum, where no keyless quote venue exists, so
their exit cost is modelled from on-chain depth and labelled `modelled`.
The model overstates cost on concentrated-liquidity venues: on live BONK it
said 7.2% where the quote said 2.3%. The report prints that ratio rather
than hiding it. On-chain depth and volume also leave out centralized
exchanges, so time-to-exit reads conservatively long.

**The model interpreter is checked, not trusted, and it is still a model.**
Code drops any token a post never names, discards any rationale that is not
a verbatim quote, and drops any post containing text aimed at a model. It
cannot tell whether a reading is *wise*. On the first live run it read a
bare price print ("Ethereum: $2,398 -1.18%") as bearish 0.7. The prompt has
since been tightened, and that run stays as recorded. Readings are frozen
into each decision, so replay never calls the model. The keyword
interpreter remains the default for fixtures and tests, and the fallback
when the model fails.

**The injection guard is a pattern, not a proof.** It catches text that
addresses a model directly ("ignore your previous rules", "respond with
bullish"). A determined attacker could phrase around it. The other checks
still apply in that case: the token must be named in the post, and the
decision engine still needs two independent voices.

**The Echo Index covers one corner of the market.** Fifteen public Telegram
news channels over fourteen days. It found almost no echo inflation there
(1.005x), and it found a real bug in Hanko's echo detector (D-14). It says
nothing about X influencers, where copy-paste shilling may look very
different. Rewrites of one press release still count as separate voices.
For opinions that rule is right; for news it is generous.

**X evidence costs money per call.** A live `x_search` costs about $0.05,
including reasoning. The public pages therefore never trigger one: `/try`
calls RYO and the keyless venues, and `/workbench` and `/drill` replay
recorded or synthetic inputs. The full pipeline runs live from the CLI,
under your own credentials.

**An `ANY_POINT_IN_WINDOW` falsifier is only as good as the samples it was
given.** `--samples` logs one reading per sweep pass, so its resolution is
however often the sweep runs. A breach shorter than the gap between two
passes can land between samples and go unseen. The review states how many
samples it checked and the span they cover. It does not yet refuse to grade
a coverage gap that is wide relative to the falsifier's own horizon.

**Reported evidence quality has an unmeasured floor.** The quality components
(completeness, freshness, corroboration, independence) measure whether
evidence exists, is recent, is corroborated and is independent, not whether
it is true. A confidently wrong but well-corroborated claim scores the same
as a right one. Only the falsifier check, after the fact, tests a claim
against what happened.
