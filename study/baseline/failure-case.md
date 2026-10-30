# SOL: a refusal that was proved wrong

The original decision is `dec_a3054fea45628213172e73f6` in `runs/run_836b976720f63dc0/decisions.jsonl`, sealed on 23 Oct 2026 at 18:05 UTC. Run `hanko verify-run runs/run_836b976720f63dc0.json` to replay its committed inputs. The manifest is anchored in Bitcoin block 972,817.

SOL was ABSTAIN, at zero size. Only one independent voice was present. Evidence quality was 0.173 against a required 0.4; freshness was 0.002486. The refusal recorded a specific reason to reconsider: independent voices greater than one at review, or 24-hour volume rising 50%.

The review in `runs/run_836b976720f63dc0/reviews.jsonl`, recorded on 28 Oct at 10:52 UTC, found two independent voices. That crossed the first committed condition, so the result is FALSIFIED. Volume did not cross its separate threshold. The review was late, after the 26 Oct deadline; the voice count is a late review-time observation, not proof of the voice count at the original deadline.

The extra voice invalidated the refusal's stated convergence assumption. It did not prove every entry gate had cleared: evidence quality, direction, conviction and exit capacity must still be checked. The falsifier's original phrase "verdict flips" is stronger than that evidence supports. This is a limitation of its wording, preserved here rather than edited out of the old commitment.

No automatic policy learning is claimed. The engine evaluates fresh evidence under the same published policy; a review does not silently rewrite its thresholds. The original model reading also included stale posts. Scheduled sweeps now restrict readings to the last 24 hours, with that filter recorded in the run, while retaining raw evidence for replay. That is an engineering correction, not proof of improved returns or an adjustment caused by this review.

The price and liquidity series has a 12.5-hour initial gap. A held check means no breach was found in the available samples, not continuous coverage. The review observations and sample trail are committed beside the decision so those gaps remain inspectable.
