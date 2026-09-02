from pathlib import Path

from web3dgamebench.pricing import estimate_official_cost, load_pricing, normalize_usage


ROOT = Path(__file__).resolve().parents[1]


def test_codex_cached_tokens_are_a_subset_of_input() -> None:
    usage = normalize_usage(
        {"inputTokens": 1000, "cachedTokens": 800, "outputTokens": 100},
        "codex-jsonl-v1",
    )
    assert usage["uncachedInputTokens"] == 200
    assert usage["totalTokens"] == 1100


def test_pi_cached_tokens_are_a_separate_bucket() -> None:
    usage = normalize_usage(
        {"inputTokens": 200, "cachedTokens": 800, "outputTokens": 100},
        "pi-jsonl-v1",
    )
    assert usage["uncachedInputTokens"] == 200
    assert usage["totalTokens"] == 1100


def test_official_cost_uses_cache_and_output_rates() -> None:
    result = estimate_official_cost(
        load_pricing(ROOT),
        "gpt-5.6-terra",
        {"inputTokens": 1_000_000, "cachedTokens": 800_000, "outputTokens": 100_000},
        "codex-jsonl-v1",
        "2026-08-30T12:00:00+00:00",
    )
    assert result["total"] == 1.76
    assert result["usage"]["totalTokens"] == 1_100_000


def test_fable_cost_uses_official_prompt_cache_rates() -> None:
    result = estimate_official_cost(
        load_pricing(ROOT),
        "claude-fable-5-1",
        {
            "inputTokens": 732,
            "cachedTokens": 661_037,
            "cacheWriteTokens": 101_921,
            "outputTokens": 91_355,
        },
        "claude-jsonl-v1",
        "2026-09-02T16:33:21+00:00",
    )
    assert result["total"] == 6.014342
    assert result["ratesPerMillion"] == {
        "input": 10.0,
        "cachedInput": 0.25,
        "cacheWrite": 12.5,
        "output": 50.0,
    }


def test_deepseek_weekend_run_uses_off_peak_rates() -> None:
    result = estimate_official_cost(
        load_pricing(ROOT),
        "deepseek-v4-flash",
        {"inputTokens": 1_000_000, "outputTokens": 1_000_000},
        "pi-jsonl-v1",
        "2026-08-30T07:00:00+00:00",
    )
    assert result["pricingTier"] == "off-peak"
    assert result["total"] == 0.88
