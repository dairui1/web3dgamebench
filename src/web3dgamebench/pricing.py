from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any


class PricingError(RuntimeError):
    pass


def load_pricing(root: Path) -> dict[str, Any]:
    path = root / "configs/pricing.toml"
    if not path.is_file():
        raise PricingError(f"pricing config not found: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def normalize_usage(usage: dict[str, Any], trace_format: str) -> dict[str, int]:
    cached = int(usage.get("cachedInputTokens", usage.get("cachedTokens", 0)) or 0)
    cache_write = int(usage.get("cacheWriteTokens", 0) or 0)
    output = int(usage.get("outputTokens", 0) or 0)
    if "uncachedInputTokens" in usage:
        uncached = int(usage.get("uncachedInputTokens") or 0)
    else:
        raw_input = int(usage.get("inputTokens", 0) or 0)
        # Codex/OpenAI reports cached input as a subset of input_tokens. Claude and
        # Pi report their cache buckets separately from ordinary input.
        uncached = max(0, raw_input - cached) if trace_format == "codex-jsonl-v1" else raw_input
    return {
        "uncachedInputTokens": uncached,
        "cachedInputTokens": cached,
        "cacheWriteTokens": cache_write,
        "outputTokens": output,
        "reasoningTokens": int(usage.get("reasoningTokens", 0) or 0),
        "totalTokens": uncached + cached + cache_write + output,
    }


def _deepseek_tier(created_at: str | None) -> str:
    if not created_at:
        return "off-peak"
    try:
        stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return "off-peak"
    if stamp.weekday() >= 5:
        return "off-peak"
    hour = stamp.hour + stamp.minute / 60
    return "peak" if 1 <= hour < 4 or 6 <= hour < 10 else "off-peak"


def estimate_official_cost(
    pricing: dict[str, Any],
    model: str,
    usage: dict[str, Any],
    trace_format: str,
    created_at: str | None,
) -> dict[str, Any]:
    model_pricing = (pricing.get("models") or {}).get(model)
    if not model_pricing:
        raise PricingError(f"official pricing is not configured for model: {model}")
    normalized = normalize_usage(usage, trace_format)
    tier = "standard"
    multiplier = 1.0
    if model == "deepseek-v4-flash":
        tier = _deepseek_tier(created_at)
        multiplier = float(model_pricing.get("peak_multiplier", 1)) if tier == "peak" else 1.0
    unit = int((pricing.get("pricing") or {}).get("unit_tokens", 1_000_000))
    rates = {
        "input": float(model_pricing["input"]) * multiplier,
        "cachedInput": float(model_pricing["cached_input"]) * multiplier,
        "cacheWrite": float(model_pricing.get("cache_write", model_pricing["input"])) * multiplier,
        "output": float(model_pricing["output"]) * multiplier,
    }
    total = (
        normalized["uncachedInputTokens"] * rates["input"]
        + normalized["cachedInputTokens"] * rates["cachedInput"]
        + normalized["cacheWriteTokens"] * rates["cacheWrite"]
        + normalized["outputTokens"] * rates["output"]
    ) / unit
    metadata = pricing.get("pricing") or {}
    result: dict[str, Any] = {
        "currency": metadata.get("currency", "USD"),
        "estimated": True,
        "total": round(total, 6),
        "usage": normalized,
        "ratesPerMillion": rates,
        "pricingTier": tier,
        "priceAsOf": metadata.get("as_of"),
        "source": model_pricing["source"],
        "sourceLabel": model_pricing["source_label"],
    }
    if model_pricing.get("note"):
        result["note"] = model_pricing["note"]
    return result
