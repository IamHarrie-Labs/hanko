from scripts.compare_baseline import baseline_enters, endpoint


def test_baseline_counts_authors_but_needs_bullish_weight():
    record = {"convergence": {"distinct_authors": 2}, "readings": [
        {"stance": "bullish", "conviction": 0.5}, {"stance": "bearish", "conviction": 0.5}]}
    assert not baseline_enters(record)
    record["readings"][1]["conviction"] = 0.4
    assert baseline_enters(record)
    record["convergence"]["distinct_authors"] = 1
    assert not baseline_enters(record)


def test_endpoint_excludes_late_prices_and_rejects_stale_readings():
    record = {"commitment": {"decided_at": "2026-10-01T00:00:00Z", "review_at": "2026-10-04T00:00:00Z"}, "market": {"price_usd": 100}}
    review = {"observations": {"samples": [
        {"at": "2026-10-03T23:00:00Z", "metrics": {"price_usd": 101}},
        {"at": "2026-10-04T01:00:00Z", "metrics": {"price_usd": 10}}]}}
    value = endpoint(record, review)
    assert abs(value[0] - 0.01) < 1e-9
    assert value[2] == 1
    review["observations"]["samples"][0]["at"] = "2026-10-03T00:00:00Z"
    assert endpoint(record, review) is None
