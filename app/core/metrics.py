from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

CLASSIFICATION_JOBS = Counter(
    "classification_jobs_total",
    "Total classification jobs by terminal status.",
    labelnames=("status", "tenant"),
    registry=REGISTRY,
)

CLASSIFICATION_LATENCY = Histogram(
    "classification_latency_seconds",
    "End-to-end latency from enqueue to terminal status.",
    labelnames=("tenant",),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)

LLM_CALL_LATENCY = Histogram(
    "llm_call_latency_seconds",
    "LLM call latency.",
    labelnames=("provider", "model"),
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
    registry=REGISTRY,
)

LLM_CALL_RESULTS = Counter(
    "llm_call_results_total",
    "LLM call outcomes.",
    labelnames=("provider", "model", "result"),
    registry=REGISTRY,
)

INTERACTION_CHECKS = Counter(
    "interaction_checks_total",
    "Drug-drug interaction checks.",
    labelnames=("safe",),
    registry=REGISTRY,
)

RATE_LIMIT_REJECTED = Counter(
    "rate_limit_rejected_total",
    "Requests rejected by the rate limiter.",
    labelnames=("identity_kind",),
    registry=REGISTRY,
)

CLASSIFICATION_BATCHES = Counter(
    "classification_batches_total",
    "Classification batches submitted.",
    labelnames=("tenant",),
    registry=REGISTRY,
)
