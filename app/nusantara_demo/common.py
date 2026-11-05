"""Shared plumbing: AM tokens, OBO exchange, lineage events."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any

import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://apim-gateway:8082")
AM_TOKEN_URL = os.environ.get("AM_TOKEN_URL", "http://gateway:8092/gamma/oauth/token")
TOWER_URL = os.environ.get("TOWER_URL", "http://nusantara-control-tower:8830")

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

TRACE_HEADER = "X-Nusantara-Trace-Id"
GW_TX_HEADER = "X-Gravitee-Transaction-Id"

USER_POLICIES = {
    "siti.claims": "POL-8842-001",
    "agus.dev": "POL-DEV-001",
    "budi.ops": "POL-7711-002",
}

STAFF_SCOPES = ["profile", "email", "claims:read"]
DEV_SCOPES = ["profile", "email", "code:read"]


def jwt_claims(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def bearer(headers: Any) -> str | None:
    value = headers.get("authorization") or headers.get("Authorization") or ""
    return value[7:] if value.lower().startswith("bearer ") else None


def actor_chain(claims: dict) -> list[str]:
    chain, act = [], claims.get("act")
    while isinstance(act, dict):
        chain.append(act.get("sub", "?"))
        act = act.get("act")
    return chain


def principal(token: str | None) -> dict:
    c = jwt_claims(token) if token else {}
    chain = actor_chain(c)
    username = c.get("preferred_username") or c.get("username")
    return {
        "sub": c.get("sub"),
        "username": username,
        "client_id": c.get("client_id") or c.get("aud"),
        "scope": c.get("scope", ""),
        "actors": chain,
        "delegated": bool(chain),
        "kind": "human-delegated" if chain else ("human" if username else "service-account"),
        "policy_id": USER_POLICIES.get(username or ""),
        "exp": c.get("exp"),
        "jti": (c.get("jti") or "")[:12],
    }


class TokenError(RuntimeError):
    pass


async def _token(form: dict) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(AM_TOKEN_URL, data=form)
    if r.status_code != 200:
        raise TokenError(f"AM token endpoint {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


async def password_token(username: str, password: str, client_id: str, secret: str) -> str:
    return await _token({
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": client_id,
        "client_secret": secret,
        "scope": "openid profile email",
    })


async def client_credentials(client_id: str, secret: str, scopes: list[str]) -> str:
    return await _token({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
        "scope": " ".join(scopes),
    })


async def exchange_on_behalf_of(
    subject_token: str, client_id: str, secret: str, allowed_scopes: list[str]
) -> str:
    held = set((jwt_claims(subject_token).get("scope") or "").split())
    scope = " ".join(s for s in allowed_scopes if s in held) or "profile email"
    actor = await client_credentials(client_id, secret, allowed_scopes)
    return await _token({
        "grant_type": TOKEN_EXCHANGE,
        "client_id": client_id,
        "client_secret": secret,
        "subject_token": subject_token,
        "subject_token_type": ACCESS_TOKEN_TYPE,
        "actor_token": actor,
        "actor_token_type": ACCESS_TOKEN_TYPE,
        "scope": scope,
    })


def hop(trace_id: str, component: str, via: str, label: str, *, status: str = "ok",
        token: str | None = None, detail: str = "", http_status: int | None = None,
        gateway_tx: str | None = None, target: str | None = None, tool: str | None = None,
        latency_ms: int | None = None, usage: dict | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "trace_id": trace_id,
        "component": component,
        "target": target,
        "via": via,
        "label": label,
        "status": status,
        "http_status": http_status,
        "principal": principal(token) if token else None,
        "tool": tool,
        "detail": detail,
        "gateway_tx": gateway_tx,
        "latency_ms": latency_ms,
        "usage": usage,
    }


async def emit(event: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            await client.post(f"{TOWER_URL}/api/audit", json=event)
    except Exception:
        pass


def usd_cost(usage: dict | None, model: str) -> float:
    if not usage:
        return 0.0
    inp = int(usage.get("prompt_tokens") or 0)
    out = int(usage.get("completion_tokens") or 0)
    if "qwen" in model.lower():
        return inp * 0.00000008 + out * 0.00000015
    if "claude" in model.lower():
        return inp * 0.000003 + out * 0.000015
    if "gpt" in model.lower():
        return inp * 0.0000025 + out * 0.00001
    return inp * 0.0000002 + out * 0.0000006


async def emit_safe(event: dict) -> None:
    try:
        await emit(event)
    except Exception:
        pass
