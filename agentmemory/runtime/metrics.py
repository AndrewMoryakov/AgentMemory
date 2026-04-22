"""In-process metrics collection for AgentMemory.

Exposes counters, latency histograms, and OpenRouter usage (tokens and an
estimated cost) with Prometheus text-format rendering so external scrapers
can attach later without restructuring the server. Everything is kept in
memory; restart wipes history.

Design choices:
- No external dependency (no prometheus_client) — this is a small surface
  and the format is stable enough to emit by hand.
- Histogram uses fixed bucket boundaries tuned for memory-ops latencies
  (sub-second LLM roundtrips dominate, with a long tail for embeddings).
- Cost estimation uses a lookup table seeded with OpenRouter's public
  pricing for the shipped defaults. Unknown models default to zero so
  totals stay informative even when pricing data is absent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


# Latency buckets in seconds. Covers fast in-memory operations through to
# multi-second LLM roundtrips. Edit if you observe most traffic landing in
# a single bucket.
_LATENCY_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"),
)


# OpenRouter pricing (USD per 1M tokens) for the shipped defaults. Numbers
# are approximate — update when pricing changes. A model absent from this
# table contributes 0 to cost totals but still counts tokens.
_PRICING_USD_PER_MTOKENS: dict[str, dict[str, float]] = {
    # Keys match what OpenRouter returns in the response `model` field.
    # OpenRouter sometimes returns the short model name without the vendor
    # prefix ("gemini-embedding-2-preview") and sometimes with version
    # suffix ("gemma-4-31b-it-20260402"); list both forms where relevant.
    "google/gemma-4-31b-it": {"prompt": 0.15, "completion": 0.30},
    "gemma-4-31b-it": {"prompt": 0.15, "completion": 0.30},
    "google/gemini-embedding-2-preview": {"prompt": 0.10, "completion": 0.0},
    "gemini-embedding-2-preview": {"prompt": 0.10, "completion": 0.0},
    "google/gemini-embedding-001": {"prompt": 0.10, "completion": 0.0},
    "gemini-embedding-001": {"prompt": 0.10, "completion": 0.0},
    "openai/text-embedding-3-small": {"prompt": 0.02, "completion": 0.0},
    "text-embedding-3-small": {"prompt": 0.02, "completion": 0.0},
    "openai/text-embedding-3-large": {"prompt": 0.13, "completion": 0.0},
    "text-embedding-3-large": {"prompt": 0.13, "completion": 0.0},
}


def _normalize_model_key(raw: str) -> str:
    """OpenRouter may append a date-suffix like "-20260402" to the returned
    model id. Strip it so pricing/accounting works against stable keys.
    """
    if "-20" in raw and raw.rsplit("-20", 1)[-1].isdigit():
        return raw.rsplit("-20", 1)[0]
    return raw


@dataclass
class _Histogram:
    buckets: list[int] = field(default_factory=lambda: [0] * len(_LATENCY_BUCKETS_SECONDS))
    count: int = 0
    sum_seconds: float = 0.0

    def observe(self, seconds: float) -> None:
        self.count += 1
        self.sum_seconds += seconds
        for idx, boundary in enumerate(_LATENCY_BUCKETS_SECONDS):
            if seconds <= boundary:
                self.buckets[idx] += 1
                break


@dataclass
class _OperationSnapshot:
    ok: int
    errors: int
    latency_count: int
    latency_sum_seconds: float
    latency_p50: float | None
    latency_p95: float | None
    latency_p99: float | None


@dataclass
class _UsageSnapshot:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class _MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._op_ok: dict[str, int] = {}
        self._op_err: dict[tuple[str, str], int] = {}
        self._op_latency: dict[str, _Histogram] = {}
        self._event_counts: dict[str, int] = {}
        self._model_tokens_prompt: dict[str, int] = {}
        self._model_tokens_completion: dict[str, int] = {}
        self._started_at = time.time()

    def record_operation(self, *, name: str, status: str, duration_seconds: float, error_type: str | None = None) -> None:
        with self._lock:
            if status == "ok":
                self._op_ok[name] = self._op_ok.get(name, 0) + 1
            else:
                key = (name, error_type or "Unknown")
                self._op_err[key] = self._op_err.get(key, 0) + 1
            histogram = self._op_latency.setdefault(name, _Histogram())
            histogram.observe(max(duration_seconds, 0.0))

    def record_event(self, *, name: str) -> None:
        with self._lock:
            self._event_counts[name] = self._event_counts.get(name, 0) + 1

    def record_llm_usage(self, *, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        if not model:
            return
        normalized = _normalize_model_key(model)
        with self._lock:
            self._model_tokens_prompt[normalized] = self._model_tokens_prompt.get(normalized, 0) + max(int(prompt_tokens), 0)
            self._model_tokens_completion[normalized] = self._model_tokens_completion.get(normalized, 0) + max(int(completion_tokens), 0)

    def operations_snapshot(self) -> dict[str, _OperationSnapshot]:
        with self._lock:
            names = set(self._op_ok.keys()) | {k[0] for k in self._op_err.keys()} | set(self._op_latency.keys())
            result: dict[str, _OperationSnapshot] = {}
            for name in names:
                ok = self._op_ok.get(name, 0)
                errors = sum(c for (n, _t), c in self._op_err.items() if n == name)
                histogram = self._op_latency.get(name)
                p50 = p95 = p99 = None
                if histogram and histogram.count > 0:
                    p50 = _quantile(histogram, 0.50)
                    p95 = _quantile(histogram, 0.95)
                    p99 = _quantile(histogram, 0.99)
                result[name] = _OperationSnapshot(
                    ok=ok,
                    errors=errors,
                    latency_count=histogram.count if histogram else 0,
                    latency_sum_seconds=histogram.sum_seconds if histogram else 0.0,
                    latency_p50=p50,
                    latency_p95=p95,
                    latency_p99=p99,
                )
            return result

    def errors_snapshot(self) -> dict[tuple[str, str], int]:
        with self._lock:
            return dict(self._op_err)

    def events_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._event_counts)

    def usage_snapshot(self) -> dict[str, _UsageSnapshot]:
        with self._lock:
            models = set(self._model_tokens_prompt) | set(self._model_tokens_completion)
            out: dict[str, _UsageSnapshot] = {}
            for model in models:
                prompt = self._model_tokens_prompt.get(model, 0)
                completion = self._model_tokens_completion.get(model, 0)
                cost = _estimate_cost_usd(model=model, prompt_tokens=prompt, completion_tokens=completion)
                out[model] = _UsageSnapshot(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=prompt + completion,
                    estimated_cost_usd=cost,
                )
            return out

    def summary(self) -> dict[str, Any]:
        ops = self.operations_snapshot()
        events = self.events_snapshot()
        usage = self.usage_snapshot()
        total_cost = sum(u.estimated_cost_usd for u in usage.values())
        return {
            "uptime_seconds": time.time() - self._started_at,
            "operations": {
                name: {
                    "ok": snap.ok,
                    "errors": snap.errors,
                    "latency_count": snap.latency_count,
                    "latency_avg_ms": round((snap.latency_sum_seconds / snap.latency_count) * 1000, 3)
                    if snap.latency_count
                    else None,
                    "latency_p50_ms": round(snap.latency_p50 * 1000, 3) if snap.latency_p50 is not None else None,
                    "latency_p95_ms": round(snap.latency_p95 * 1000, 3) if snap.latency_p95 is not None else None,
                    "latency_p99_ms": round(snap.latency_p99 * 1000, 3) if snap.latency_p99 is not None else None,
                }
                for name, snap in sorted(ops.items())
            },
            "events": {name: count for name, count in sorted(events.items())},
            "usage": {
                model: {
                    "prompt_tokens": snap.prompt_tokens,
                    "completion_tokens": snap.completion_tokens,
                    "total_tokens": snap.total_tokens,
                    # 9-dp keeps sub-cent cost visible (embeddings on a single
                    # query are fractions of a cent), 6-dp was rounding them
                    # to 0 and hiding the mechanism.
                    "estimated_cost_usd": round(snap.estimated_cost_usd, 9),
                }
                for model, snap in sorted(usage.items())
            },
            "total_estimated_cost_usd": round(total_cost, 9),
        }

    def prometheus_text(self) -> str:
        lines: list[str] = []
        ops = self.operations_snapshot()
        errors = self.errors_snapshot()
        events = self.events_snapshot()

        lines.append("# HELP agentmemory_operation_ok_total Number of successful operations.")
        lines.append("# TYPE agentmemory_operation_ok_total counter")
        for name, snap in sorted(ops.items()):
            lines.append(f'agentmemory_operation_ok_total{{operation="{_esc(name)}"}} {snap.ok}')

        lines.append("# HELP agentmemory_operation_error_total Number of failed operations by error type.")
        lines.append("# TYPE agentmemory_operation_error_total counter")
        for (name, error_type), count in sorted(errors.items()):
            lines.append(
                f'agentmemory_operation_error_total{{operation="{_esc(name)}",error_type="{_esc(error_type)}"}} {count}'
            )

        lines.append("# HELP agentmemory_event_total Auxiliary event counters.")
        lines.append("# TYPE agentmemory_event_total counter")
        for name, count in sorted(events.items()):
            lines.append(f'agentmemory_event_total{{event="{_esc(name)}"}} {count}')

        lines.append("# HELP agentmemory_operation_latency_seconds Operation latency histogram.")
        lines.append("# TYPE agentmemory_operation_latency_seconds histogram")
        for name, snap in sorted(ops.items()):
            histogram = self._op_latency.get(name)
            if histogram is None:
                continue
            cumulative = 0
            for idx, boundary in enumerate(_LATENCY_BUCKETS_SECONDS):
                cumulative += histogram.buckets[idx]
                le_label = "+Inf" if boundary == float("inf") else repr(boundary)
                lines.append(
                    f'agentmemory_operation_latency_seconds_bucket{{operation="{_esc(name)}",le="{le_label}"}} {cumulative}'
                )
            lines.append(
                f'agentmemory_operation_latency_seconds_count{{operation="{_esc(name)}"}} {histogram.count}'
            )
            lines.append(
                f'agentmemory_operation_latency_seconds_sum{{operation="{_esc(name)}"}} {histogram.sum_seconds}'
            )

        usage = self.usage_snapshot()
        lines.append("# HELP agentmemory_llm_tokens_total Tokens consumed by LLM / embedder per model.")
        lines.append("# TYPE agentmemory_llm_tokens_total counter")
        for model, snap in sorted(usage.items()):
            lines.append(
                f'agentmemory_llm_tokens_total{{model="{_esc(model)}",kind="prompt"}} {snap.prompt_tokens}'
            )
            lines.append(
                f'agentmemory_llm_tokens_total{{model="{_esc(model)}",kind="completion"}} {snap.completion_tokens}'
            )
        lines.append("# HELP agentmemory_llm_cost_usd Estimated spend in USD by model.")
        lines.append("# TYPE agentmemory_llm_cost_usd counter")
        for model, snap in sorted(usage.items()):
            lines.append(
                f'agentmemory_llm_cost_usd{{model="{_esc(model)}"}} {snap.estimated_cost_usd:.9f}'
            )
        return "\n".join(lines) + "\n"


def _quantile(histogram: _Histogram, q: float) -> float | None:
    if histogram.count == 0:
        return None
    target = q * histogram.count
    cumulative = 0
    for idx, boundary in enumerate(_LATENCY_BUCKETS_SECONDS):
        cumulative += histogram.buckets[idx]
        if cumulative >= target:
            return boundary if boundary != float("inf") else _LATENCY_BUCKETS_SECONDS[-2]
    return None


def _estimate_cost_usd(*, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _PRICING_USD_PER_MTOKENS.get(model)
    if pricing is None:
        return 0.0
    per_mtok_prompt = pricing.get("prompt", 0.0)
    per_mtok_completion = pricing.get("completion", 0.0)
    return (prompt_tokens * per_mtok_prompt + completion_tokens * per_mtok_completion) / 1_000_000


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


_REGISTRY = _MetricsRegistry()


def record_operation(*, name: str, status: str, duration_seconds: float, error_type: str | None = None) -> None:
    _REGISTRY.record_operation(
        name=name, status=status, duration_seconds=duration_seconds, error_type=error_type
    )


def record_event(*, name: str) -> None:
    _REGISTRY.record_event(name=name)


def record_llm_usage(*, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    _REGISTRY.record_llm_usage(model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def summary() -> dict[str, Any]:
    return _REGISTRY.summary()


def prometheus_text() -> str:
    return _REGISTRY.prometheus_text()


class _TimedCall:
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self._started = 0.0

    def __enter__(self) -> "_TimedCall":
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, _tb) -> None:
        duration = time.perf_counter() - self._started
        if exc is None:
            record_operation(name=self.operation_name, status="ok", duration_seconds=duration)
        else:
            record_operation(
                name=self.operation_name,
                status="error",
                duration_seconds=duration,
                error_type=exc_type.__name__ if exc_type else "Unknown",
            )
        # Do not suppress the exception.
        return None


def timed(operation_name: str) -> _TimedCall:
    return _TimedCall(operation_name)
