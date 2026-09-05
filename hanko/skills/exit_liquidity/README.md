# exit_liquidity

**Track 3 · New Skills**

> The six live RYO tools all answer *is this worth entering?* Nothing tells
> you whether you can get *out* of it.

## The gap

Confirmed against the real, authenticated catalog (`GET /api/mcp/tools`), not
the hackathon's own public tool list: six tools exist, and every one of them
answers a version of the entry question. `analyze_token` and `deep_analysis`
say what a token is doing. `compare_tokens` ranks candidates. There is no
safety tool on the real catalog at all — the closest thing to a risk signal
is a qualitative `intelligence.risks` list, not a score.

None of the six answer *can this position be closed, and what does closing it
cost?*

That's the number that turns research into a trade. A token can look clean on
every measured signal and still be a trap:

```
ILLIQUID  TOKENA  confidence moderate
  exiting $50,000 costs 10.0%  ($5,000)
  largest exit at 1% slippage: $4,545
  largest exit at 3% slippage: $13,918
  or exit over 2.9h at 10% of volume
  modelled with cpmm_v1, not observed
```

That token clears every measured signal `analyze_token` and `deep_analysis`
report. It is also a position you cannot close at size without giving back a
tenth of it. Position size chosen without exit cost is a guess with a number
attached.

## What it returns

| | |
|---|---|
| `estimate` | Price impact and dollar cost of exiting the size you asked about |
| `max_size_usd` | Largest exit clearing 1%, 3%, and your own ceiling |
| `hours_to_exit` | How long a patient exit takes instead, at a volume participation cap |
| `curve` | Cost across a size ladder scaled to the pool, not a fixed dollar ladder |
| `model` | The model id and every assumption behind the figures |
| `inputs` | Each number used, and the tool and key path it was read from |
| `gaps` | Each input it wanted and did not get |

## The honesty convention, applied to a model

Two rules here are stricter than the platform requires, because this tool has a
particular way of being dangerous.

**Modelled is not measured.** No order book is observed anywhere in this skill,
so nothing it returns is presented as observed, and `confidence` has no `HIGH`
value at all — the enum simply doesn't contain one. The model, its assumptions,
and the point past which it stops being valid all travel with the answer:

```json
"model": {
  "id": "cpmm_v1",
  "assumptions": [
    "pool behaves as constant-product (x*y=k)",
    "reported liquidity is total value locked, i.e. twice one side",
    "all liquidity is reachable in a single route",
    "no fees, no MEV, no price movement during the exit",
    "mid price at the time of the quote"
  ]
}
```

Past 25% of the pool a constant-product curve stops describing a real venue —
routers split, other pools absorb flow, market makers step away. The tool says so
and downgrades its own confidence rather than extrapolating a number it doesn't
believe.

**A missing input produces no number.** If liquidity is unavailable, the slippage
fields are `null` and the verdict is `unknown`. Never zero — a zero here reads as
*free to exit*, which is the most dangerous fabrication this particular tool could
make.

```
UNKNOWN  TOKENA  confidence none
  ? liquidity_usd unavailable; exit cost cannot be modelled and is
    reported as null rather than zero
```

## The model

Constant-product pool, `x·y = k`. Selling `dx` returns `dy = y·dx/(x+dx)`, so
against the mid price the shortfall is:

```
slippage = dx / (x + dx) = f / (1 + f)      where f = dx / x
```

Reported liquidity is taken as total value locked, twice one side, so a notional
`S` gives `f = 2S / liquidity_usd`. Every step is an assumption that can be
wrong, which is why they're listed in the response rather than buried here.

## Use

Standalone, against a facts file:

```bash
hanko exit-liquidity TOKENA --size 50000 --market fixtures/market_tokena.json
```

Live, over MCP:

```bash
hanko exit-liquidity TOKENA --size 50000 --max-slippage 3
```

The tool definition, ready to register on an MCP server:

```bash
hanko exit-liquidity TOKENA --schema
```

As a library:

```python
from hanko.skills.exit_liquidity import assess, call, describe
```

`assess()` is pure — same facts and parameters in, same report out — so it is
fully testable offline and its output can be replayed rather than re-fetched.

## Composing with an agent

The skill is also the size gate inside Hanko's decision engine, using the same
model rather than a second copy of the arithmetic, so the number the agent sizes
on and the number the tool publishes cannot drift apart:

```
ABSTAIN TOKENA  size 0.0%
  + quality_floor: evidence quality 0.75 clears 0.4
  x exit_liquidity: evidence warranted 3.28% ($3,279) but exiting that costs
    20.78%, over the 3.0% ceiling; capped to 0.39% ($387)
  x size_floor: warranted size 0.387% is below the floor of 0.5%
```

Every measured evidence check passed. The agent declined because it could
not get out — and said so, in those words.

## Tests

28 tests, offline, no network:

- The curve against closed-form constant-product values, and the inverse
- Time-to-exit scaling with size and volume
- `OK` / `TIGHT` / `ILLIQUID` boundaries, and the caller's ceiling overriding them
- Missing liquidity returning null rather than zero; zero liquidity treated as unusable
- Missing volume dropping only the time estimate
- Model-validity flagging and confidence downgrade past 25% of pool
- Untraceable inputs lowering confidence
- A deep-but-inactive pool being called out
- Schema validity, percent-argument conversion, and JSON round-tripping

```bash
pytest tests/test_exit_liquidity.py
```
