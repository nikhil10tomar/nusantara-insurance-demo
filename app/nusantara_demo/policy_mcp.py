"""Policy & claims MCP — upstream system of record (NIK, policy numbers)."""
from __future__ import annotations

import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .common import GW_TX_HEADER, TRACE_HEADER, USER_POLICIES, bearer, emit, hop, principal

POLICIES = {
    "POL-8842-001": {
        "holder_username": "siti.claims",
        "holder_name": "Siti Rahayu",
        "nik": "3175012345670001",
        "product": "Asuransi Jiwa Nusantara Plus",
        "premium_idr": 2_450_000,
        "status": "active",
        "claims_open": 1,
    },
    "POL-DEV-001": {
        "holder_username": "agus.dev",
        "holder_name": "Agus Wijaya (test)",
        "nik": "3201234567890123",
        "product": "Sandbox policy for engineering",
        "premium_idr": 0,
        "status": "test",
        "claims_open": 0,
    },
    "POL-7711-002": {
        "holder_username": "budi.ops",
        "holder_name": "Budi Santoso",
        "nik": "3301987654321009",
        "product": "Asuransi Kesehatan Keluarga",
        "premium_idr": 890_000,
        "status": "active",
        "claims_open": 0,
    },
}

CLAIMS = {
    "POL-8842-001": [
        {"id": "CLM-2026-0142", "type": "Hospital cash", "amount_idr": 5_000_000, "status": "under_review"},
    ],
    "POL-7711-002": [],
    "POL-DEV-001": [],
}

REPO_FILES = {
    "claims-api/README.md": "# Claims API\nHandles POL-* validation and OJK reporting hooks.\n",
    "claims-api/openapi.yaml": "openapi: 3.0.0\ninfo:\n  title: Claims API\n  version: 1.0.0\n",
    "pii-masking/rules.json": '{"nik_pattern":"\\\\d{16}","policy_pattern":"POL-[0-9]{4}-[0-9]{3}"}\n',
}

mcp = FastMCP(
    "nusantara-policy",
    instructions="Internal insurance tools: policies, claims, codebase (dev), payouts.",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8831")),
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _caller(ctx: Context) -> tuple[dict, str, str | None, str | None]:
    req = getattr(ctx.request_context, "request", None)
    headers = req.headers if req is not None else {}
    token = bearer(headers)
    return principal(token), token or "", headers.get(TRACE_HEADER), headers.get(GW_TX_HEADER)


async def _record(ctx: Context, tool: str, outcome: str) -> dict:
    who, token, trace_id, gw_tx = _caller(ctx)
    await emit(hop(trace_id or "untraced", "nusantara-policy-mcp", "core-system",
                   f"{tool} executed", token=token or None, tool=tool, detail=outcome, gateway_tx=gw_tx))
    chain = " ← ".join(who["actors"]) if who["actors"] else "(direct)"
    return {
        "executed_for_sub": who["sub"],
        "executed_for_username": who["username"],
        "agent_chain": chain,
        "token_kind": who["kind"],
    }


@mcp.tool()
async def get_policy_status(policy_id: str, ctx: Context) -> dict:
    """Return policy status and holder summary for a POL-* id."""
    pid = (policy_id or "").strip().upper()
    meta = await _record(ctx, "get_policy_status", f"policy={pid}")
    row = POLICIES.get(pid)
    if not row:
        return {**meta, "found": False, "policy_id": pid}
    return {
        **meta,
        "found": True,
        "policy_id": pid,
        "status": row["status"],
        "product": row["product"],
        "holder_name": row["holder_name"],
        "premium_idr": row["premium_idr"],
        "nik": row["nik"],
        "claims_open": row["claims_open"],
    }


@mcp.tool()
async def list_claims_for_policy(policy_id: str, ctx: Context) -> dict:
    """List open claims for a policy."""
    pid = (policy_id or "").strip().upper()
    meta = await _record(ctx, "list_claims_for_policy", f"policy={pid}")
    return {**meta, "policy_id": pid, "claims": CLAIMS.get(pid, [])}


@mcp.tool()
async def summarize_coverage(policy_id: str, ctx: Context) -> dict:
    """Plain-language coverage summary for customer-facing staff agents."""
    pid = (policy_id or "").strip().upper()
    meta = await _record(ctx, "summarize_coverage", f"policy={pid}")
    row = POLICIES.get(pid)
    if not row:
        return {**meta, "found": False}
    return {
        **meta,
        "found": True,
        "policy_id": pid,
        "summary": (
            f"{row['product']} is {row['status']}. "
            f"Annual premium IDR {row['premium_idr']:,}. "
            f"Holder NIK on file ends …{row['nik'][-4:]}."
        ),
    }


@mcp.tool()
async def search_codebase(query: str, ctx: Context) -> dict:
    """Search internal repo index (Claude Code / developer agents)."""
    q = (query or "").strip().lower()
    meta = await _record(ctx, "search_codebase", f"q={q[:80]}")
    hits = [p for p in REPO_FILES if q in p.lower() or q in REPO_FILES[p].lower()]
    return {**meta, "query": query, "paths": hits[:10]}


@mcp.tool()
async def get_repo_file(path: str, ctx: Context) -> dict:
    """Read a file from the claims engineering monorepo."""
    p = (path or "").strip().lstrip("/")
    meta = await _record(ctx, "get_repo_file", f"path={p}")
    content = REPO_FILES.get(p)
    if content is None:
        return {**meta, "found": False, "path": p}
    return {**meta, "found": True, "path": p, "content": content}


@mcp.tool()
async def initiate_payout(policy_id: str, amount_idr: int, ctx: Context) -> dict:
    """Finance-only payout initiation — not exposed on governed composites."""
    pid = (policy_id or "").strip().upper()
    meta = await _record(ctx, "initiate_payout", f"policy={pid} amount={amount_idr}")
    return {
        **meta,
        "status": "queued",
        "policy_id": pid,
        "amount_idr": amount_idr,
        "note": "This tool exists upstream for batch jobs; staff/dev agents should not see it.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/reset", methods=["POST"])
async def reset(_request):
    return JSONResponse({"ok": True})


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
