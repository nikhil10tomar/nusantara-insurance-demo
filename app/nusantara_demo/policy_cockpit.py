"""Map gateway LLM responses to presenter-friendly policy cards."""
from __future__ import annotations

import json
import os
from typing import Any

GAMMA_BASE = os.environ.get("GAMMA_BASE_URL", "http://gamma.localhost/environments/default")
LLM_API_NAME = os.environ.get("NUSANTARA_LLM_API_NAME", "Nusantara LLM Gateway")

# Static policy catalog (matches provision/gateway.py flows on ACME clone)
POLICY_CATALOG = [
    {"id": "domain-block", "name": "Shadow IT domain block", "flow": "Shadow IT domain block", "policy": "groovy"},
    {"id": "model-router", "name": "Regulated routing (Qwen vs cloud)", "flow": "Complexity-Based Model Router", "policy": "groovy"},
    {"id": "prompt-guard", "name": "Malicious Prompt Guard Rails", "flow": "Prompt", "policy": "ai-prompt-guard-rails"},
    {"id": "pii", "name": "PII filtering (NIK, policy numbers, email)", "flow": "Prompt", "policy": "pii-filtering"},
    {"id": "budget", "name": "Budget-Wise (monetary spend limit)", "flow": "Prompt", "policy": "monetary-spend-limit"},
    {"id": "token-rl", "name": "Token rate limit", "flow": "Prompt", "policy": "token-ratelimit"},
]


def _header(headers: dict[str, str], key: str) -> str:
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v if isinstance(v, str) else str(v)
    return ""


def gamma_links(transaction_id: str | None) -> dict[str, str]:
    tx = (transaction_id or "").strip()
    traces = f"{GAMMA_BASE}/observe/traces"
    logs = f"{GAMMA_BASE}/observe/logs"
    api = f"{GAMMA_BASE}/apis"
    policy_studio = f"{GAMMA_BASE}/apis"  # presenter picks Nusantara LLM Gateway → Design
    out = {
        "gamma_traces": traces,
        "gamma_logs": logs,
        "gamma_apis": api,
        "gamma_hint": f"Filter logs by API «{LLM_API_NAME}»" + (f" and transaction {tx}" if tx else ""),
        "policy_studio_hint": f"APIs → {LLM_API_NAME} → Plans → flows (PII, Budget-Wise, domain block, prompt guard)",
    }
    if tx:
        out["gamma_logs_search"] = f"{logs}?query={tx}"
    return out


def interpret_llm_response(
    status: int,
    headers: dict[str, str],
    body: Any,
) -> dict[str, Any]:
    """Turn one gateway round-trip into policy cards for the UI."""
    body_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    tx = _header(headers, "x-gravitee-transaction-id")
    model = _header(headers, "x-llm-proxy-model") or _header(headers, "x-gravitee-routed-model")
    residency = _header(headers, "x-data-residency")
    cache = _header(headers, "x-semantic-cache")

    applied: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []

    applied.append({
        "id": "entry",
        "name": "Nusantara LLM Gateway (entry)",
        "state": "passed" if status < 400 else "failed",
        "detail": f"HTTP {status}" + (f" · model {model}" if model else ""),
    })

    if status >= 400:
        msg = ""
        if isinstance(body, dict):
            msg = json.dumps(body.get("message") or body.get("error") or body)[:240]
        else:
            msg = body_text[:240]
        if "chatgpt.com" in body_text.lower() or "shadow" in msg.lower():
            blocked.append({"id": "domain-block", "name": "Shadow IT domain block", "detail": msg or "403"})
        elif status == 429 or "budget" in msg.lower() or "limit" in msg.lower():
            blocked.append({"id": "budget", "name": "Budget-Wise (monetary spend limit)", "detail": msg})
        else:
            blocked.append({"id": "prompt-guard", "name": "Gateway guardrail / policy", "detail": msg})
    else:
        if residency == "on-prem-id" or (model and "qwen" in model.lower()):
            applied.append({
                "id": "model-router",
                "name": "Regulated routing → on-prem Qwen",
                "detail": model or "qwen2.5-7b-instruct",
            })
        elif model:
            applied.append({
                "id": "model-router",
                "name": "Cloud model route",
                "detail": model,
            })

        if "[REDACTED]" in body_text or "***" in body_text:
            applied.append({
                "id": "pii",
                "name": "PII filtering",
                "detail": "Sensitive tokens masked in model payload (check Gamma logs for request phase).",
            })
        else:
            watch.append({
                "id": "pii",
                "name": "PII filtering",
                "detail": "Active on gateway; add NIK/email in prompt to see [REDACTED] in response.",
            })

        watch.append({"id": "prompt-guard", "name": "Malicious Prompt Guard Rails", "detail": "Enabled on Prompt flow"})
        watch.append({"id": "budget", "name": "Budget-Wise", "detail": "Monetary spend limit on this API plan"})

        if cache and cache.upper() != "MISS":
            applied.append({"id": "cache", "name": "Semantic cache", "detail": cache})

    return {
        "transaction_id": tx,
        "status": status,
        "model": model,
        "residency": residency,
        "applied": applied,
        "blocked": blocked,
        "watch": watch,
        "catalog": POLICY_CATALOG,
        "gamma": gamma_links(tx),
    }
