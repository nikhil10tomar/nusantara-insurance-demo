"""Staff + developer assistants — governed LLM + composite MCP."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
from openai import BadRequestError, OpenAI, RateLimitError

from .common import (
    DEV_SCOPES,
    GATEWAY_URL,
    GW_TX_HEADER,
    STAFF_SCOPES,
    TRACE_HEADER,
    USER_POLICIES,
    TokenError,
    emit,
    exchange_on_behalf_of,
    hop,
    password_token,
    usd_cost,
)

PASSWORD = os.environ.get("DEMO_PASSWORD", "NusantaraDemo#2026")
TOWER_CLIENT = os.environ.get("TOWER_CLIENT_ID", "nusantara-control-tower")
TOWER_SECRET = os.environ.get("TOWER_CLIENT_SECRET", "nusantara-control-tower-secret")

PERSONAS = {
    "staff": {
        "username_key": "siti.claims",
        "agent_client": "nusantara-staff-agent",
        "agent_secret": "nusantara-staff-agent-secret",
        "scopes": STAFF_SCOPES,
        "llm_base": f"{GATEWAY_URL}/nusantara-llm",
        "llm_model": os.environ.get("STAFF_LLM_MODEL", "gemini-2.0-flash"),
        "mcp_url": f"{GATEWAY_URL}/nusantara-staff-mcp",
        "system": (
            "You are PT Asuransi Nusantara's internal claims assistant. "
            "Use MCP tools for policy facts — never invent NIK or policy numbers. "
            "You cannot initiate payouts."
        ),
    },
    "dev": {
        "username_key": "agus.dev",
        "agent_client": "nusantara-dev-agent",
        "agent_secret": "nusantara-dev-agent-secret",
        "scopes": DEV_SCOPES,
        "llm_base": f"{GATEWAY_URL}/nusantara-llm",
        "llm_model": os.environ.get("DEV_LLM_MODEL", "claude-sonnet-4-6"),
        "mcp_url": f"{GATEWAY_URL}/nusantara-dev-mcp",
        "system": (
            "You are a developer copilot (Claude Code style) for the claims engineering monorepo. "
            "Use repo tools only for code questions; use get_policy_status only for the sandbox test policy."
        ),
    },
}


class McpClient:
    def __init__(self, url: str, token: str, trace_id: str, gateway_tx: str | None):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            TRACE_HEADER: trace_id,
            "MCP-Protocol-Version": "2025-06-18",
        }
        if gateway_tx:
            self.headers[GW_TX_HEADER] = gateway_tx
        self.tools: list[dict] = []

    @staticmethod
    def _parse(r: httpx.Response) -> dict:
        if "text/event-stream" in r.headers.get("content-type", ""):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text[:400]}

    async def rpc(self, client: httpx.AsyncClient, method: str, params: dict | None = None) -> tuple[httpx.Response, dict]:
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": uuid.uuid4().hex[:8]}
        r = await client.post(self.url, json=body, headers=self.headers)
        if r.headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        return r, self._parse(r)

    async def open(self, client: httpx.AsyncClient) -> None:
        r, body = await self.rpc(client, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "nusantara-agent", "version": "1.0.0"},
        })
        if r.status_code != 200:
            raise RuntimeError(f"MCP init {r.status_code}: {r.text[:200]}")
        await self.rpc(client, "notifications/initialized", {})
        _, listed = await self.rpc(client, "tools/list", {})
        self.tools = (listed.get("result") or {}).get("tools") or []

    def openai_tools(self) -> list[dict]:
        out = []
        for t in self.tools:
            out.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description") or t["name"],
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                },
            })
        return out

    async def call_tool(self, client: httpx.AsyncClient, name: str, arguments: dict) -> tuple[int, str, str | None]:
        r, body = await self.rpc(client, "tools/call", {"name": name, "arguments": arguments})
        tx = r.headers.get(GW_TX_HEADER)
        if r.status_code != 200:
            return r.status_code, r.text[:500], tx
        result = body.get("result") or {}
        text = ""
        for c in result.get("content") or []:
            if c.get("text"):
                text += c["text"]
        if not text and result.get("structuredContent"):
            text = json.dumps(result["structuredContent"])
        return 200, text or json.dumps(result), tx


async def run_chat(
    persona: str,
    username: str,
    message: str,
    *,
    trace_id: str | None = None,
    gateway_tx: str | None = None,
) -> dict:
    cfg = PERSONAS.get(persona, PERSONAS["staff"])
    trace_id = trace_id or uuid.uuid4().hex[:12]
    hops: list[dict] = []
    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    model_used = cfg["llm_model"]

    async def record(h: dict) -> None:
        hops.append(h)
        await emit(h)

    policy_id = USER_POLICIES.get(username, "")
    try:
        user_token = await password_token(username, PASSWORD, TOWER_CLIENT, TOWER_SECRET)
        await record(hop(trace_id, "nusantara-ui", "am:password", "Employee signed in (subject on token)",
                         token=user_token, detail=username))
        agent_token = await exchange_on_behalf_of(
            user_token, cfg["agent_client"], cfg["agent_secret"], cfg["scopes"]
        )
        await record(hop(trace_id, cfg["agent_client"], "am:token-exchange",
                         "RFC 8693 — human stays sub, agent in act", token=agent_token,
                         detail=f"persona={persona}"))
    except TokenError as e:
        await record(hop(trace_id, cfg["agent_client"], "am:token-exchange", "Failed", status="error", detail=str(e)))
        return {"text": str(e), "hops": hops, "cost_usd": 0.0}

    llm = OpenAI(base_url=cfg["llm_base"], api_key="gravitee-demo")
    extra_headers = {TRACE_HEADER: trace_id}
    if gateway_tx:
        extra_headers[GW_TX_HEADER] = gateway_tx

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": cfg["system"]},
        {"role": "system", "content": f"Employee: {username}. Own policy id (if any): {policy_id or 'n/a'}."},
        {"role": "user", "content": message},
    ]

    mcp = McpClient(cfg["mcp_url"], agent_token, trace_id, gateway_tx)
    async with httpx.AsyncClient(timeout=90) as http:
        await mcp.open(http)
        tool_names = [t["name"] for t in mcp.tools]
        await record(hop(trace_id, cfg["agent_client"], "gateway:mcp-composite",
                         f"Composite MCP — {len(tool_names)} tools",
                         token=agent_token, detail=", ".join(tool_names)))

        if "initiate_payout" in tool_names:
            await record(hop(trace_id, cfg["agent_client"], "gateway:mcp-composite",
                             "Unexpected payout tool visible", status="warning"))

        oai_tools = mcp.openai_tools()
        for turn in range(8):
            started = time.perf_counter()
            try:
                completion = llm.chat.completions.create(
                    model=cfg["llm_model"],
                    messages=messages,
                    tools=oai_tools or None,
                    extra_headers=extra_headers,
                )
            except BadRequestError as e:
                await record(hop(trace_id, cfg["agent_client"], "gateway:llm", "Blocked at gateway",
                                 status="blocked", detail=str(e)[:240], target="nusantara-llm"))
                return {
                    "text": "Gateway blocked that request (PII, shadow-IT domain, or prompt guard). Check Gamma logs.",
                    "hops": hops,
                    "cost_usd": usd_cost(total_usage, model_used),
                    "blocked": True,
                }
            except RateLimitError as e:
                await record(hop(trace_id, cfg["agent_client"], "gateway:llm", "Budget-Wise / rate limit",
                                 status="blocked", detail=str(e)[:240], target="nusantara-llm"))
                return {
                    "text": "Budget-Wise cap or token rate limit reached — uncontrolled AI spend stops here.",
                    "hops": hops,
                    "cost_usd": usd_cost(total_usage, model_used),
                    "rate_limited": True,
                }
            latency = int((time.perf_counter() - started) * 1000)
            msg = completion.choices[0].message
            usage = completion.usage
            u = {}
            if usage:
                u = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
                for k in total_usage:
                    total_usage[k] += int(u.get(k) or 0)
            model_used = completion.model or cfg["llm_model"]
            await record(hop(trace_id, cfg["agent_client"], "gateway:llm", f"LLM Proxy turn {turn + 1}",
                             token=agent_token, latency_ms=latency, target="nusantara-llm",
                             usage=u or None, detail=f"model={model_used}"))

            if msg.tool_calls:
                messages.append(msg.model_dump())
                for tc in msg.tool_calls:
                    fn = tc.function
                    args = json.loads(fn.arguments or "{}")
                    t0 = time.perf_counter()
                    status, text, tx = await mcp.call_tool(http, fn.name, args)
                    tlat = int((time.perf_counter() - t0) * 1000)
                    st = "ok" if status == 200 else "blocked"
                    await record(hop(trace_id, cfg["agent_client"], "gateway:mcp", f"tools/call {fn.name}",
                                     status=st, token=agent_token, tool=fn.name, http_status=status,
                                     latency_ms=tlat, gateway_tx=tx, detail=text[:320]))
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
                continue

            return {
                "text": msg.content or "",
                "hops": hops,
                "cost_usd": usd_cost(total_usage, model_used),
                "usage": total_usage,
                "model": model_used,
                "tools_visible": tool_names,
                "persona": persona,
            }

    return {"text": "Too many turns.", "hops": hops, "cost_usd": usd_cost(total_usage, model_used)}
