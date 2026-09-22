---
name: hanko-exit-liquidity
description: Answer a plain-English question about what it costs to exit a crypto position, or how large a position a token can absorb, using RYO's live market data. Use when the user asks things like "what does it cost to exit $50k of BONK", "how liquid is SOL right now", "how long would it take to sell out of this position", or names a token together with a position size. Returns a modelled OK / TIGHT / ILLIQUID / UNKNOWN verdict, backed entirely by figures the script prints, never invented by the model.
---

# hanko-exit-liquidity

This skill runs Hanko's `exit_liquidity` Track 3 tool: a constant-product
cost model that prices what it takes to close a position, not just whether
to open one. It runs the real pipeline and reports only what it returns.

## The one rule

**Every number in your answer must come from the command's own output.** Do
not compute, estimate, or restate a slippage percentage, a cost figure, or a
time-to-exit yourself, and do not soften a `null` into an implied zero. If
`liquidity_usd` is unavailable, the tool reports the verdict as `unknown` and
the cost fields as `null` on purpose, because a zero there reads as "free to
exit," the one fabrication this tool exists to refuse. Report `null` as
`null`, and say the figure is unavailable rather than guessing at it. This
mirrors the project's own honesty convention (see `DECISIONS.md`, D-05).

## How to run it

From the repository root:

```bash
hanko exit-liquidity SOL --size 50000
```

Live, against the real RYO MCP endpoint (needs `RYO_MCP_URL` and
`RYO_MCP_KEY` set). Add `--json` for machine-readable output, or omit
`--size` to get the cost curve and slippage ceilings without pricing one
specific position.

Offline, against a fixture, no credentials needed:

```bash
hanko exit-liquidity TOKENA --size 50000 --market fixtures/market_tokena.json
```

Output is the same either way: a verdict line, then whatever the model could
measure. A representative live result, run against BONK:

```
UNKNOWN  BONK  confidence none
  price $0.00000337 · 24h volume $137,702,816  (analyze_token)
  exit over 34.9h at 10% of volume
  this market absorbs $573,762 per hour at that cap
  waiting that long is exposed to ~8.6% price drift at this market's volatility
  turnover 46.4% of market cap per day; this position is 6.732% of cap
  ? liquidity_usd unavailable; exit cost cannot be modelled and is
    reported as null rather than zero
  modelled with cpmm_v1, not observed
```

Time to exit, hourly capacity, price drift and turnover all came from real
volume data even though price impact could not be modelled. Report all of
them; do not treat the one missing figure as a reason to withhold the rest.

## Interpreting the verdict

- **OK**: exiting the requested size stays inside the caller's slippage
  ceiling (3% by default).
- **TIGHT**: exits, but costs more than the ceiling allows.
- **ILLIQUID**: exit cost at this size is severe; the position is a large
  fraction of the pool.
- **UNKNOWN**: not enough input to say anything about price impact. This is
  the normal case against live data: RYO has never published pool depth for
  any token checked, so a live `OK`/`TIGHT`/`ILLIQUID` has not yet been
  observed (see `LIMITATIONS.md`).

`confidence` never reads `high`. No order book is observed anywhere in this
skill, so nothing it returns is presented as observed rather than modelled.

## What this skill must not do

- Never invent a liquidity, slippage, or cost figure the command did not
  print.
- Never turn a `null` liquidity figure into `0`, or describe a position as
  "free to exit" when the figure is simply unavailable.
- Never override the verdict word (`OK`/`TIGHT`/`ILLIQUID`/`UNKNOWN`) the
  command actually returned.
- If the command errors, or the RYO credential is not configured, report
  that directly rather than substituting a plausible-sounding number.
