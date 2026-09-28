# Sealing a run

`hanko seal` is `hanko sweep` plus one guarantee `hanko sweep` does not make
on its own: that what gets published about a run cannot later be shown to
have left something out. A single sealed decision only proves its own
commitment existed before its outcome. It proves nothing about the
decisions around it -- publish ten and reveal the three that went well, and
every one of those three still verifies. The dishonesty lives in the seven
that were never mentioned, not in anything a hash can catch. A run
manifest is the fix: every watchlist entry, numbered, in the order the
sweep actually reached it, including the ones that errored, abstained, or
passed.

## Before the first run: pre-register

Commit `watchlist.json` and note the policy in force (`Policy()`'s
defaults, unless a non-default one is being used) *before* running `hanko
seal` against them for the first time. The point of pre-registration is
that the schedule and the rules cannot be quietly adjusted after seeing
how a run turned out -- a watchlist edited mid-series is a different claim
than a watchlist held constant, and `watchlist_digest` inside every
manifest is what would catch a silent change either way.

## Daily

```bash
hanko seal --watchlist watchlist.json --samples samples.jsonl --ots \
  --repo-url https://github.com/IamHarrie-Labs/hanko
```

One pass: decide on every watchlist entry, grade whatever the ledgers say
is due, then write `runs/run_<id>.json` -- the numbered manifest -- and
(with `--ots`) `runs/run_<id>.json.ots`, an OpenTimestamps proof anchoring
`manifest_digest` to public Bitcoin-backed calendars.

`--samples samples.jsonl` matters for more than convenience: it is what
lets an `ANY_POINT_IN_WINDOW` falsifier ([D-13](DECISIONS.md#d-13-a-falsifier-said-within-72h-and-only-checked-the-last-tick))
catch a price or liquidity breach that recovers before a decision comes up
for review. Pass it every day, to the same file, for the whole series.

Commit `runs/run_<id>.json` and its `.ots` file. These are the public
record -- unlike `decisions.jsonl`, `reviews.jsonl`, and `samples.jsonl`,
which stay local and gitignored, `runs/` is meant to be published.

Then post `manifest_digest` and the run's verdict counts (the command
prints ready-to-paste text under `--- post text ---`) somewhere with a
public, independent timestamp of its own -- X, if that is where this is
being announced. Posting is not something this tool does for you: X
credentials are not something this pipeline holds or should hold.

## What each proof actually shows

Two independent claims, not one:

- **A tweet, posted publicly, roughly when it says it was.** Ordinary
  social proof: people who saw it at the time can attest to that, but the
  platform's own timestamp is not independently checkable by a third
  party years later.
- **`runs/run_<id>.json.ots`, once a Bitcoin block confirms it.** A
  cryptographic proof, checkable by anyone, that `manifest_digest` existed
  no later than that block. `hanko ots-status runs/run_<id>.json.ots`
  reports `pending` until that happens (usually a few hours after
  stamping) and `confirmed` after. A `pending` proof is not weaker
  evidence than a confirmed one turns out to be -- it is evidence of a
  different, not-yet-complete thing, and is reported as such rather than
  implied to already be settled.

Together: a human-readable public announcement, anchored independently of
the platform that carried it.

## 72 hours later: review

```bash
hanko sweep --watchlist watchlist.json --samples samples.jsonl \
  --now <the review instant>
```

(`hanko sweep` grades whatever the ledgers say is due; `hanko seal` does
the same review pass, on top of also sealing that day's new decisions --
run either, depending on whether this pass should also open new positions.)

Check `runs/run_<id>.json` against `decisions.jsonl`: every `decision_id`
listed there should be in the ledger, and `hanko audit` should reproduce
each one exactly from the snapshot store. This is the reveal -- the
manifest published on day 1 already said what would be checked; this step
is where the checking actually happens, in public.

## What is not automated yet

Publishing `decisions.jsonl`, `reviews.jsonl`, and the relevant snapshot
objects alongside each run's manifest, so a third party can run `hanko
audit` themselves from a bare clone without re-running the original
sweep, is still a manual step (copy the ledger lines and the referenced
snapshot files into the run's own folder before committing). Automating
that -- a `hanko seal --publish-bundle` that writes exactly the slice of
each gitignored ledger a given run touched -- is the natural next piece of
this pipeline, not yet built.
