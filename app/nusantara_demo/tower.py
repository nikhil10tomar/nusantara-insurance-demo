"""Nusantara Insurance — presenter control tower."""
from __future__ import annotations

import collections
import os
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .assist_agent import run_chat
from .common import GATEWAY_URL, hop
from .policy_cockpit import interpret_llm_response

HERE = Path(__file__).parent
GAMMA_TRACE = os.environ.get(
    "GAMMA_TRACE_URL",
    "http://gamma.localhost/environments/default/observe/traces",
)

app = FastAPI(title="Nusantara Insurance AI Gateway Demo")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

EVENTS: collections.deque = collections.deque(maxlen=4000)
SESSION_COST: dict[str, float] = {}


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/claude")
async def claude_browser():
    """Browser chat with Claude model id through Nusantara LLM Gateway + live policy panel."""
    return FileResponse(HERE / "static" / "claude.html")


@app.post("/api/audit")
async def audit(event: dict):
    EVENTS.append(event)
    return {"ok": True}


@app.get("/api/traces")
async def traces(limit: int = 80):
    rows = list(EVENTS)[-limit:]
    rows.reverse()
    return {"events": rows}


@app.get("/api/health")
async def health():
    checks = []
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in [
            ("Policy MCP", "http://nusantara-policy-mcp:8831/health"),
            ("Mock Qwen", "http://nusantara-mock-qwen:8832/health"),
            ("Mock cloud LLM", "http://nusantara-mock-cloud:8833/health"),
            ("Gateway", f"{GATEWAY_URL}/"),
        ]:
            try:
                r = await client.get(url)
                checks.append({"name": name, "ok": r.status_code < 500, "status": r.status_code})
            except Exception as e:
                checks.append({"name": name, "ok": False, "error": str(e)[:120]})
    return {"checks": checks, "all_ok": all(c.get("ok") for c in checks)}


@app.post("/api/chat")
async def chat(body: dict):
    persona = (body.get("persona") or "staff").strip()
    user = (body.get("user") or "siti.claims").strip()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    trace_id = body.get("trace_id") or uuid.uuid4().hex[:12]
    await audit(hop(trace_id, "nusantara-ui", "ui:chat", f"{persona} message", detail=message[:200]))
    result = await run_chat(persona, user, message, trace_id=trace_id)
    cost = float(result.get("cost_usd") or 0.0)
    SESSION_COST[trace_id] = SESSION_COST.get(trace_id, 0.0) + cost
    gw_tx = next((h.get("gateway_tx") for h in reversed(result.get("hops") or []) if h.get("gateway_tx")), None)
    return {
        **result,
        "trace_id": trace_id,
        "cost_usd": round(cost, 6),
        "cost_usd_display": f"${cost:.4f}",
        "otel": {
            "trace_id": trace_id,
            "gravitee_transaction_id": gw_tx,
            "gamma_traces_url": GAMMA_TRACE,
        },
    }


async def _llm_via_gateway(
    prompt: str,
    model: str,
    *,
    client_id: str = "nusantara-budget-demo",
    trace_id: str | None = None,
) -> tuple[int, dict[str, str], dict | str]:
    headers = {"Content-Type": "application/json", "X-Client-Id": client_id}
    if trace_id:
        headers["X-Nusantara-Trace-Id"] = trace_id
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{GATEWAY_URL}/nusantara-llm/chat/completions",
            headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        )
    hdrs = dict(r.headers)
    try:
        body_json = r.json()
    except Exception:
        body_json = {"raw": r.text[:500]}
    return r.status_code, hdrs, body_json


def _assistant_text(body: dict | str) -> str:
    if isinstance(body, str):
        return body[:2000]
    try:
        choices = body.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            return (msg.get("content") or "").strip()
    except (TypeError, KeyError, IndexError):
        pass
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return ""


@app.post("/api/demo/llm")
async def demo_llm(body: dict):
    prompt = body.get("prompt") or ""
    model = body.get("model") or "gemini-2.0-flash"
    status, hdrs, body_json = await _llm_via_gateway(prompt, model)
    cockpit = interpret_llm_response(status, hdrs, body_json)
    return {"status": status, "headers": hdrs, "body": body_json, "cockpit": cockpit}


@app.post("/api/claude/chat")
async def claude_chat(body: dict):
    """Browser Claude UI — same gateway path, returns policy cockpit for the presenter."""
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    model = (body.get("model") or "claude-sonnet-4-6").strip()
    trace_id = body.get("trace_id") or uuid.uuid4().hex[:12]
    await audit(hop(trace_id, "claude-browser", "ui:claude-chat", "Browser message", detail=message[:200]))
    status, hdrs, body_json = await _llm_via_gateway(
        message,
        model,
        client_id="nusantara-claude-browser",
        trace_id=trace_id,
    )
    cockpit = interpret_llm_response(status, hdrs, body_json)
    await audit(hop(
        trace_id, "claude-browser", "gateway:nusantara-llm",
        "LLM round-trip", detail=f"status={status} model={cockpit.get('model')}",
        gateway_tx=cockpit.get("transaction_id"),
    ))
    return {
        "trace_id": trace_id,
        "status": status,
        "body": body_json,
        "assistant_text": _assistant_text(body_json),
        "cockpit": cockpit,
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8830")), log_level="info")


if __name__ == "__main__":
    main()
