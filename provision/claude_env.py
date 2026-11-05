#!/usr/bin/env python3
"""Export shell env so Claude Code CLI uses Nusantara LLM Gateway (all gateway policies apply).

Usage (from nusantara-insurance-demo directory):

  eval "$(python3 provision/claude_env.py)"          # keyless → gateway Open plan
  eval "$(python3 provision/claude_env.py --delegated)"  # developer OBO JWT (audit in Gamma)

  claude
  # or: claude -p --model claude-sonnet-4-6 'Your question'

Before first use, wire real Anthropic upstream (optional but recommended):

  python3 provision/wire_claude_upstream.py

Without wire_claude_upstream, cloud models still hit the local mock (policies still run).
"""
from __future__ import annotations

import argparse
import shlex
import sys

from _http import call, jwt_claims

import os

AM_GW = os.environ.get("AM_GW_TOKEN_URL", "http://localhost:8092/gamma/oauth/token")
GATEWAY_LLM = os.environ.get("GATEWAY_LLM_URL", "http://localhost:8082/nusantara-llm").rstrip("/")
PASSWORD = "NusantaraDemo#2026"
TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"


def tok(form: dict) -> dict:
    return call("POST", AM_GW, form=form)


def delegated_dev_token() -> str:
    """Agus (developer) subject + nusantara-dev-agent actor — same story as Claude Code + AM."""
    user = tok({
        "grant_type": "password",
        "username": "agus.dev",
        "password": PASSWORD,
        "client_id": "nusantara-control-tower",
        "client_secret": "nusantara-control-tower-secret",
        "scope": "openid profile email code:read",
    })["access_token"]
    actor = tok({
        "grant_type": "client_credentials",
        "client_id": "nusantara-dev-agent",
        "client_secret": "nusantara-dev-agent-secret",
        "scope": "profile email code:read",
    })["access_token"]
    scope = "profile email code:read"
    return tok({
        "grant_type": TOKEN_EXCHANGE,
        "client_id": "nusantara-dev-agent",
        "client_secret": "nusantara-dev-agent-secret",
        "subject_token": user,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": actor,
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": scope,
    })["access_token"]


def write_exports(*, delegated: bool) -> None:
    lines = [
        f"export ANTHROPIC_BASE_URL={shlex.quote(GATEWAY_LLM)}",
        "unset ANTHROPIC_API_KEY",
    ]
    if delegated:
        token = delegated_dev_token()
        lines.append(f"export ANTHROPIC_AUTH_TOKEN={shlex.quote(token)}")
        who = jwt_claims(token).get("preferred_username") or "agus.dev"
        lines.append(f"export NUSANTARA_CLI_USER={shlex.quote(who)}")
    else:
        lines.append("unset ANTHROPIC_AUTH_TOKEN")
        # Keyless Open plan on Nusantara LLM Gateway; SDK still wants a non-empty key sometimes.
        lines.append("export ANTHROPIC_API_KEY=gravitee-demo")
    lines.append(f"export NUSANTARA_GAMMA_LOGS={shlex.quote('http://gamma.localhost/environments/default/observe/logs')}")
    lines.append(f"export NUSANTARA_LLM_API={shlex.quote('Nusantara LLM Gateway')}")
    sys.stdout.write("\n".join(lines) + "\n")


def check_gateway() -> int:
    import json
    import urllib.error
    import urllib.request

    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "Reply with exactly: gateway-ok"}],
    }).encode()
    req = urllib.request.Request(
        f"{GATEWAY_LLM}/v1/messages",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": "gravitee-demo", "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"OK HTTP {r.status} — Nusantara LLM Gateway reachable", file=sys.stderr)
            return 0
    except urllib.error.HTTPError as e:
        print(f"Gateway HTTP {e.code}: {e.read()[:200].decode()}", file=sys.stderr)
        return 1


def main() -> None:
    p = argparse.ArgumentParser(description="Env for Claude CLI → Gravitee Nusantara LLM Gateway")
    p.add_argument("--delegated", action="store_true", help="Use developer OBO JWT (ANTHROPIC_AUTH_TOKEN)")
    p.add_argument("--check", action="store_true", help="Test gateway /v1/messages (does not print exports)")
    args = p.parse_args()
    if args.check:
        raise SystemExit(check_gateway())
    write_exports(delegated=args.delegated)


if __name__ == "__main__":
    main()
