"""Per-project LLM token usage and cost reporting."""

from datetime import datetime, timezone
from pathlib import Path

from core.utils import read_json, write_json


# Update these rates when a provider changes its public API pricing.
# Values are currency units per one million tokens.
MODEL_PRICING = {
    "openai": {
        "gpt-5.6-sol": {"currency": "USD", "input": 5.0, "cached_input": 0.5, "output": 30.0},
        "gpt-5.6-terra": {"currency": "USD", "input": 2.0, "cached_input": 0.2, "output": 12.0},
        "gpt-5.6-luna": {"currency": "USD", "input": 0.2, "cached_input": 0.02, "output": 1.2},
    },
    "ali": {
        "qwen3.7-max": {"currency": "CNY", "input": 12.0, "cached_input": 2.4, "output": 36.0},
    },
}


def start_llm_cost_report(path):
    path = Path(path)
    write_json(
        {
            "scope": "LLM API token usage only; excludes TTS/STT, storage, download and rendering costs.",
            "status": "running",
            "started_at": _timestamp(),
            "calls": [],
            "totals": {},
        },
        path,
        ensure_ascii=False,
        indent=2,
    )


def record_llm_usage(path, provider, stage, model, usage):
    """Append a provider-reported usage record and refresh per-currency totals."""
    if not path or usage is None:
        return
    path = Path(path)
    if not path.exists():
        start_llm_cost_report(path)

    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    cached_tokens = _usage_value(_usage_value(usage, "prompt_tokens_details"), "cached_tokens")
    cached_tokens = min(prompt_tokens, cached_tokens)
    pricing = MODEL_PRICING.get(provider, {}).get(model)
    call = {
        "stage": stage,
        "provider": provider,
        "model": model,
        "input_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": _usage_value(usage, "total_tokens") or prompt_tokens + completion_tokens,
        "recorded_at": _timestamp(),
    }
    if pricing:
        uncached_tokens = prompt_tokens - cached_tokens
        cost = (
            uncached_tokens * pricing["input"]
            + cached_tokens * pricing["cached_input"]
            + completion_tokens * pricing["output"]
        ) / 1_000_000
        call["pricing"] = pricing
        call["cost"] = round(cost, 8)
    else:
        call["cost"] = None
        call["pricing_note"] = "未配置该模型价格，只记录 token 用量。"

    report = read_json(path)
    report.setdefault("calls", []).append(call)
    report["totals"] = _totals(report["calls"])
    write_json(report, path, ensure_ascii=False, indent=2)


def finish_llm_cost_report(path):
    path = Path(path)
    if not path.exists():
        return
    report = read_json(path)
    report["status"] = "completed"
    report["completed_at"] = _timestamp()
    report["totals"] = _totals(report.get("calls", []))
    write_json(report, path, ensure_ascii=False, indent=2)


def _totals(calls):
    totals = {}
    for call in calls:
        pricing = call.get("pricing")
        if not pricing:
            continue
        currency = pricing["currency"]
        total = totals.setdefault(currency, {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        total["input_tokens"] += call["input_tokens"]
        total["cached_input_tokens"] += call["cached_input_tokens"]
        total["output_tokens"] += call["output_tokens"]
        total["cost"] += call["cost"]
    for total in totals.values():
        total["cost"] = round(total["cost"], 8)
    return totals


def _usage_value(value, field):
    if value is None:
        return 0
    if isinstance(value, dict):
        return value.get(field, 0) or 0
    return getattr(value, field, 0) or 0


def _timestamp():
    return datetime.now(timezone.utc).isoformat()
