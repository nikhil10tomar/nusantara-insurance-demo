#!/usr/bin/env python3
"""Provision Nusantara Insurance demo on local Gamma + APIM. Idempotent."""
from __future__ import annotations

import json
import os
import sys
import time

from _http import HttpError, basic, call, items

APIM = os.environ.get("APIM_URL", "http://localhost:8083")
V2 = f"{APIM}/management/v2/environments/DEFAULT"
V1 = f"{APIM}/management/organizations/DEFAULT/environments/DEFAULT"
AIM = f"{APIM}/gamma/organizations/DEFAULT/environments/DEFAULT/modules/aim"
AUTH = basic("admin", "admin")
JWKS = os.environ.get("AM_JWKS_URL", "http://gateway:8092/gamma/oidc/.well-known/jwks.json")
JWT_PLAN = "Employee JWT (delegated)"
PROTO = "2025-11-25"

MCP_UPSTREAM = os.environ.get("MCP_UPSTREAM", "http://nusantara-policy-mcp:8831/mcp")

STAFF_TOOLS = ["get_policy_status", "list_claims_for_policy", "summarize_coverage"]
DEV_TOOLS = ["search_codebase", "get_repo_file", "get_policy_status"]

POLICY_GUARD = r"""
def raw = request.content == null ? '' : request.content.toString()
if (!raw.contains('tools/call')) {
  return
}
def body = new groovy.json.JsonSlurper().parseText(raw)
if (body['method'] != 'tools/call') {
  return
}
def tool = body['params']['name']?.toString() ?: ''
def args = body['params']['arguments'] ?: [:]
def policyId = (args['policy_id'] ?: '').toString().trim().toUpperCase()
def claims = context.attributes['jwt.claims']
def user = ''
if (claims != null) {
  user = claims['preferred_username']?.toString() ?: claims.username?.toString() ?: ''
}
def allowed = [
  'siti.claims':'POL-8842-001',
  'agus.dev':'POL-DEV-001',
  'budi.ops':'POL-7711-002',
][user]
if (tool in ['get_policy_status','list_claims_for_policy','summarize_coverage'] && policyId.length() > 0) {
  if (allowed == null || policyId != allowed) {
    response.status(403)
    response.headers.put('Content-Type', ['application/json'])
    response.content = groovy.json.JsonOutput.toJson([
      message: 'Denied by Gravitee AI Gateway. Cross-policy access is blocked here — not by the LLM (PDP Law / OJK audit).',
      policy_id: policyId,
      username: user,
    ])
    return
  }
}
"""

DOMAIN_BLOCK = r"""
def raw = request.content == null ? '' : request.content.toString()
def lower = raw.toLowerCase()
def blocked = ['chatgpt.com', 'gemini.google.com', 'pastebin.com', 'discord.com/invite']
// Do not block claude.ai — Claude Code / Anthropic clients reference it in metadata and break with 500.
for (d in blocked) {
  if (lower.contains(d)) {
    response.status(403)
    response.headers.put('Content-Type', ['application/json'])
    response.content = groovy.json.JsonOutput.toJson([
      message: 'Shadow IT blocked: consumer AI or paste domains cannot appear in enterprise prompts. Route through Nusantara AI Gateway.',
      blocked_domain: d,
    ])
    return
  }
}
"""

REGULATED_ROUTER = r"""
def body = (request.content != null) ? request.content.toString() : ""
if (body.contains('"tools"') || body.contains('"tool_choice"')) {
  return
}
def lower = body.toLowerCase()
def model = "gemini-2.0-flash"
if (body ==~ /.*\\d{16}.*/ || lower.contains('nik') || lower.contains('pol-') || lower.contains('policy holder')) {
  model = "qwen2.5-7b-instruct"
  context.setAttribute("demo.data.class", "regulated")
} else if (body.contains('claude-opus-5-5')) {
  model = "claude-opus-5-5"
} else if (body.contains('claude-opus-4-8')) {
  model = "claude-opus-4-8"
} else if (lower.contains('opus') || body.contains('claude-opus')) {
  model = "claude-opus-4-6"
} else if (lower.contains('claude') || body.contains('claude-sonnet')) {
  model = "claude-sonnet-4-6"
} else if (lower.contains('gpt-4') || body.contains('gpt-4o')) {
  model = "gpt-4o"
}
context.setAttribute("llmproxy.model.override", model)
context.setAttribute("demo.routed.model", model)
"""

MODEL_GOV = {
    "prefixPolicy": {"policy": "NO_PREFIX"},
    "aliasOnly": False,
    "modelPattern": "",
}

# Claude Code sends unprefixed ids (today: claude-opus-5-5). Gateway rejects unknown models with 400.
CLOUD_LLM_MODELS = [
    {"name": "claude-opus-5-5", "inputPrice": 15.0, "outputPrice": 75.0},
    {"name": "claude-opus-4-8", "inputPrice": 15.0, "outputPrice": 75.0},
    {"name": "claude-opus-4-6", "inputPrice": 15.0, "outputPrice": 75.0},
    {"name": "claude-sonnet-4-6", "inputPrice": 3.0, "outputPrice": 15.0},
    {"name": "claude-haiku-4-5", "inputPrice": 0.8, "outputPrice": 4.0},
    {"name": "gpt-4o", "inputPrice": 2.5, "outputPrice": 10.0},
    {"name": "gemini-2.0-flash", "aliases": ["staff"], "inputPrice": 0.2, "outputPrice": 0.6},
]


def merge_cloud_llm_models(cfg: dict) -> bool:
    by_name = {m["name"]: m for m in cfg.get("models") or []}
    before = list(by_name.keys())
    for m in CLOUD_LLM_MODELS:
        by_name.setdefault(m["name"], dict(m))
    cfg["models"] = list(by_name.values())
    cfg["modelGovernance"] = dict(MODEL_GOV)
    return sorted(before) != sorted(by_name.keys())


MONETARY_CFG = {
    "subjectExpression": "{#request.headers['X-Client-Id'] != null ? #request.headers['X-Client-Id'][0] : #context.attributes['client_id']}",
    "budgetPeriod": "daily",
    "budgetAmountUsd": 50,
    "dailyLimitMessage": "Budget-Wise: daily AI spend cap reached. Contact FinOps (OJK-aligned cost control).",
    "weeklyLimitMessage": "Budget-Wise weekly cap reached.",
    "monthlyLimitMessage": "Budget-Wise monthly cap reached.",
    "inputPricePerMillionTokens": 0.4,
    "outputPricePerMillionTokens": 0.8,
    "limitExceededStatusCode": 429,
}


def api(method: str, url: str, body=None):
    return call(method, url, body, auth=AUTH, timeout=120)


def all_apis() -> list[dict]:
    return items(api("GET", f"{V2}/apis?perPage=300"))


def api_by_name(name: str) -> dict | None:
    return next((a for a in all_apis() if a.get("name") == name), None)


def ensure_apps() -> dict[str, str]:
    existing = {a["name"]: a for a in items(api("GET", f"{V1}/applications"))}
    specs = {
        "Nusantara Control Tower": ("nusantara-control-tower", "Presenter UI"),
        "Nusantara Staff Agent": ("nusantara-staff-agent", "Claims assistant"),
        "Nusantara Dev Agent": ("nusantara-dev-agent", "Claude Code stand-in"),
    }
    ids = {}
    for name, (cid, desc) in specs.items():
        app = existing.get(name)
        if not app:
            app = api("POST", f"{V1}/applications", {
                "name": name, "description": desc,
                "settings": {"app": {"type": "SIMPLE", "client_id": cid}}})
            print(f"  + application {name}")
        else:
            print(f"  = application {name}")
        ids[name] = app["id"]
    return ids


def jwt_security() -> dict:
    return {
        "type": "JWT",
        "configuration": {
            "signature": "RSA_RS256",
            "publicKeyResolver": "JWKS_URL",
            "resolverParameter": JWKS,
            "connectTimeout": 2000,
            "requestTimeout": 2000,
            "extractClaims": True,
            "propagateAuthHeader": True,
            "userClaim": "sub",
            "confirmationMethodValidation": {"ignoreMissing": True},
            "tokenTypValidation": {"enabled": False},
        },
    }


def mcp_acl_flow(tools: list[str], label: str) -> dict:
    return {
        "name": label,
        "enabled": True,
        "selectors": [{"type": "MCP", "methods": []}],
        "request": [{
            "name": "MCP ACL",
            "enabled": True,
            "policy": "mcp-acl",
            "configuration": {
                "authorizations": [{
                    "authorizedFeatures": [{
                        "type": "TOOLS",
                        "methods": ["TOOLS_LIST", "TOOLS_CALL"],
                        "patternType": "LITERAL",
                        "patternValue": ",".join(tools),
                    }],
                }],
            },
        }],
        "response": [], "subscribe": [], "publish": [], "interact": [], "connect": [], "entrypointConnect": [],
        "tags": [],
    }


def policy_guard_flow() -> dict:
    return {
        "name": "Own-policy boundary",
        "enabled": True,
        "selectors": [{"type": "MCP", "methods": ["tools/call"]}],
        "request": [{
            "name": "Nusantara policy boundary",
            "enabled": True,
            "policy": "groovy",
            "configuration": {"onRequestContentScript": POLICY_GUARD, "readContent": True},
        }],
        "response": [], "subscribe": [], "publish": [], "interact": [], "entrypointConnect": [], "tags": [],
    }


def patch_staff_policy_guard() -> None:
    """Attach own-policy groovy on staff MCP plan (prompt-injection / cross-policy demo)."""
    name = "Nusantara Staff MCP"
    a = api_by_name(name)
    if not a:
        return
    full = api("GET", f"{V2}/apis/{a['id']}")
    if full.get("flows"):
        full["flows"] = []
        for k in ("id", "crossId", "hrid", "deployedAt", "createdAt", "updatedAt", "state",
                  "deploymentState", "lifecycleState", "primaryOwner", "workflowState",
                  "disableMembershipNotifications", "originContext", "definitionContext"):
            full.pop(k, None)
        api("PUT", f"{V2}/apis/{a['id']}", full)
    plans = items(api("GET", f"{V2}/apis/{a['id']}/plans?perPage=20"))
    plan = next((p for p in plans if JWT_PLAN in (p.get("name") or "")), None)
    if not plan:
        return
    flows = [f for f in plan.get("flows") or [] if f.get("name") != "Own-policy boundary"]
    flows.append(policy_guard_flow())
    plan["flows"] = flows
    api("PUT", f"{V2}/apis/{a['id']}/plans/{plan['id']}", {
        k: plan[k] for k in ("definitionVersion", "name", "description", "security", "flows", "validation",
                             "characteristics", "tags", "commentRequired", "excludedGroups",
                             "generalConditions", "selectionRule") if k in plan})
    api("POST", f"{V2}/apis/{a['id']}/deployments", {"deploymentLabel": "nusantara-staff-boundary"})
    print(f"  ~ policy boundary on {name} plan")


def ensure_mcp_proxy(name: str, path: str, tools: list[str], description: str) -> None:
    existing = next((p for p in items(api("GET", f"{AIM}/mcp-proxies?perPage=200")) if p.get("name") == name), None)
    if not existing:
        api("POST", f"{AIM}/mcp-proxies", {
            "name": name,
            "description": description,
            "contextPath": path,
            "mode": "PROXY",
            "serverUrl": MCP_UPSTREAM,
            "transport": "streamable-http",
            "protocolVersion": PROTO,
            "upstreamAuth": {"type": "passthrough"},
            "plans": [{
                "name": JWT_PLAN,
                "security": {"type": "OAUTH2_AM", "configuration": {"scopes": []}},
            }],
            "deploy": True,
        })
        print(f"  + MCP proxy {name} → {path}")
        time.sleep(2)
    else:
        print(f"  = MCP proxy {name}")

    a = api_by_name(name)
    if not a:
        time.sleep(3)
        a = api_by_name(name)
    if not a:
        sys.exit(f"API {name} not found")
    plans = items(api("GET", f"{V2}/apis/{a['id']}/plans?perPage=20"))
    plan = next((p for p in plans if JWT_PLAN in (p.get("name") or "")), plans[0] if plans else None)
    if not plan:
        plan = api("POST", f"{V2}/apis/{a['id']}/plans", {
            "definitionVersion": "V4", "name": JWT_PLAN, "security": jwt_security(),
            "mode": "STANDARD", "validation": "AUTO", "flows": [],
        })
    plan["flows"] = [mcp_acl_flow(tools, f"Tool surface ({len(tools)} tools)")]
    api("PUT", f"{V2}/apis/{a['id']}/plans/{plan['id']}", {
        k: plan[k] for k in ("definitionVersion", "name", "description", "security", "flows", "validation",
                             "characteristics", "tags", "commentRequired", "excludedGroups",
                             "generalConditions", "selectionRule") if k in plan})
    if plan.get("status") != "PUBLISHED":
        api("POST", f"{V2}/apis/{a['id']}/plans/{plan['id']}/_publish")
    api("POST", f"{V2}/apis/{a['id']}/deployments", {"deploymentLabel": "nusantara-mcp"})
    print(f"  ~ MCP ACL on {name}")


def sync_llm_model_prefix(api_id: str) -> None:
    """Gravitee defaults to provider prefixes; clients send bare model ids (Claude Code, OpenAI SDK)."""
    full = api("GET", f"{V2}/apis/{api_id}")
    changed = False
    for group in full.get("endpointGroups") or []:
        for endpoint in group.get("endpoints") or []:
            cfg = endpoint.get("configuration") or {}
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            if cfg.get("modelGovernance") != MODEL_GOV:
                cfg["modelGovernance"] = dict(MODEL_GOV)
                changed = True
            endpoint["configuration"] = cfg
    if not changed:
        return
    for k in ("id", "crossId", "hrid", "deployedAt", "createdAt", "updatedAt", "state",
              "deploymentState", "lifecycleState", "primaryOwner", "workflowState",
              "disableMembershipNotifications", "originContext", "definitionContext"):
        full.pop(k, None)
    api("PUT", f"{V2}/apis/{api_id}", full)
    api("POST", f"{V2}/apis/{api_id}/deployments", {"deploymentLabel": "nusantara-llm-prefix"})
    print("  ~ LLM model prefix policy → NO_PREFIX")


def ensure_llm_gateway() -> None:
    name = "Nusantara LLM Gateway"
    source_name = "ACME Hotels LLMs"
    existing = api_by_name(name)
    if existing:
        print(f"  = LLM proxy {name}")
        api_id = existing["id"]
    else:
        source = api_by_name(source_name)
        if not source:
            sys.exit(f"'{source_name}' required to clone {name}")
        export = api("GET", f"{V2}/apis/{source['id']}/_export/definition")
        d = export["api"]
        for k in ("id", "crossId", "hrid", "deployedAt", "createdAt", "updatedAt", "state", "lifecycleState",
                  "primaryOwner", "workflowState", "disableMembershipNotifications"):
            d.pop(k, None)
        d["name"] = name
        d["description"] = (
            "Governed LLM front door — on-prem Qwen + cloud Claude/GPT/Gemini. "
            "PII (NIK, policy numbers), prompt guard, domain block, Budget-Wise spend."
        )
        d["listeners"][0]["paths"] = [{"path": "/nusantara-llm/", "overrideAccess": False}]
        for group in d.get("endpointGroups") or []:
            if group.get("name") != "ollama":
                continue
            eps = []
            eps.append({
                "name": "qwen-onprem",
                "type": "llm-proxy",
                "weight": 1,
                "inheritConfiguration": True,
                "configuration": {
                    "models": [{"name": "qwen2.5-7b-instruct", "aliases": ["onprem"], "inputPrice": 0.08, "outputPrice": 0.15}],
                    "provider": "OPEN_AI_COMPATIBLE",
                    "modelGovernance": dict(MODEL_GOV),
                    "target": "http://nusantara-mock-qwen:8832/v1",
                    "authentication": {"type": "NONE"},
                },
                "secondary": False,
            })
            eps.append({
                "name": "cloud-llms",
                "type": "llm-proxy",
                "weight": 1,
                "inheritConfiguration": True,
                "configuration": {
                    "models": [dict(m) for m in CLOUD_LLM_MODELS],
                    "provider": "OPEN_AI_COMPATIBLE",
                    "modelGovernance": dict(MODEL_GOV),
                    "target": "http://nusantara-mock-cloud:8833/v1",
                    "authentication": {"type": "NONE"},
                },
                "secondary": False,
            })
            group["endpoints"] = eps
            group.pop("failover", None)
        # ACME export includes real OpenAI/Anthropic/Gemini groups — drop them so demos use local mocks only.
        d["endpointGroups"] = [g for g in d.get("endpointGroups") or [] if g.get("name") == "ollama"]
        created = api("POST", f"{V2}/apis/_import/definition", {"api": d, "plans": [], "members": [], "metadata": [], "pages": []})
        api_id = created["id"]
        print(f"  + LLM proxy {name} → /nusantara-llm/ ({api_id})")

    full = api("GET", f"{V2}/apis/{api_id}")
    groups = full.get("endpointGroups") or []
    if len(groups) != 1 or groups[0].get("name") != "ollama":
        full["endpointGroups"] = [g for g in groups if g.get("name") == "ollama"]
        for group in full["endpointGroups"]:
            if group.get("name") != "ollama":
                continue
            has_qwen = any(ep.get("name") == "qwen-onprem" for ep in group.get("endpoints") or [])
            if not has_qwen:
                group["endpoints"] = [
                    {
                        "name": "qwen-onprem",
                        "type": "llm-proxy",
                        "weight": 1,
                        "inheritConfiguration": True,
                        "configuration": {
                            "models": [{"name": "qwen2.5-7b-instruct", "aliases": ["onprem"], "inputPrice": 0.08, "outputPrice": 0.15}],
                            "provider": "OPEN_AI_COMPATIBLE",
                            "target": "http://nusantara-mock-qwen:8832/v1",
                            "authentication": {"type": "NONE"},
                        },
                        "secondary": False,
                    },
                    {
                        "name": "cloud-llms",
                        "type": "llm-proxy",
                        "weight": 1,
                        "inheritConfiguration": True,
                        "configuration": {
                            "models": [dict(m) for m in CLOUD_LLM_MODELS],
                            "provider": "OPEN_AI_COMPATIBLE",
                            "modelGovernance": dict(MODEL_GOV),
                            "target": "http://nusantara-mock-cloud:8833/v1",
                            "authentication": {"type": "NONE"},
                        },
                        "secondary": False,
                    },
                ]
    models_synced = False
    for group in full.get("endpointGroups") or []:
        for ep in group.get("endpoints") or []:
            if ep.get("name") != "cloud-llms":
                continue
            cfg = ep.get("configuration") or {}
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            if merge_cloud_llm_models(cfg):
                ep["configuration"] = cfg
                models_synced = True
    for flow in full.get("flows") or []:
        if flow.get("name") != "Prompt":
            continue
        req = flow.setdefault("request", [])
        # Idempotent: each sync used to prepend another copy (still blocking claude.ai) → Claude CLI 500.
        flow["request"] = [s for s in req if s.get("name") != "Shadow IT domain block"]
        req = flow["request"]
        req.insert(0, {
            "name": "Shadow IT domain block",
            "enabled": True,
            "policy": "groovy",
            "configuration": {"onRequestContentScript": DOMAIN_BLOCK, "readContent": True},
        })
        for step in req:
            if step.get("name") == "Complexity-Based Model Router":
                script = REGULATED_ROUTER
                cfg = step.setdefault("configuration", {})
                cfg["onRequestContentScript"] = script
                cfg["script"] = script
            if step.get("name") == "Malicious Prompt Guard Rails":
                # Claude Code sends large system/tool payloads; guard often returns 400 MALICIOUS via gateway.
                step["enabled"] = os.environ.get("NUSANTARA_ENABLE_PROMPT_GUARD", "").strip() not in ("", "0", "false")
            if step.get("name") == "Toxicity Detection":
                step["enabled"] = False
            if step.get("name") == "PII Filtering":
                step["enabled"] = True
            if step.get("name") == "AI Semantic Caching":
                step["enabled"] = False
            if step.get("name") == "Token Rate Limit":
                step["enabled"] = False
            if step.get("name") == "Token Rate Limit (response)":
                step["enabled"] = False
        if not any(s.get("policy") == "monetary-spend-limit" for s in req):
            req.append({
                "name": "Budget-Wise (Monetary Spend Limit)",
                "description": "Cap USD spend per team / client id",
                "enabled": True,
                "policy": "monetary-spend-limit",
                "configuration": dict(MONETARY_CFG),
            })
        resp = flow.setdefault("response", [])
        if not any(s.get("policy") == "monetary-spend-limit" for s in resp):
            resp.insert(0, {
                "name": "Budget-Wise (record usage)",
                "enabled": True,
                "policy": "monetary-spend-limit",
                "configuration": dict(MONETARY_CFG),
            })
        for step in resp:
            if step.get("name") == "Expose Semantic Cache + Rate Limit Headers":
                step["enabled"] = True
    for k in ("id", "crossId", "hrid", "deployedAt", "createdAt", "updatedAt", "state",
              "deploymentState", "lifecycleState", "primaryOwner", "workflowState",
              "disableMembershipNotifications", "originContext", "definitionContext"):
        full.pop(k, None)
    api("PUT", f"{V2}/apis/{api_id}", full)

    plans = items(api("GET", f"{V2}/apis/{api_id}/plans?perPage=20"))
    if not plans:
        plan = api("POST", f"{V2}/apis/{api_id}/plans", {
            "definitionVersion": "V4", "name": "Open",
            "security": {"type": "KEY_LESS", "configuration": {}},
            "mode": "STANDARD", "validation": "AUTO", "flows": []})
        api("POST", f"{V2}/apis/{api_id}/plans/{plan['id']}/_publish")
    else:
        plan = plans[0]
        if plan.get("status") != "PUBLISHED":
            api("POST", f"{V2}/apis/{api_id}/plans/{plan['id']}/_publish")

    full["lifecycleState"] = "PUBLISHED"
    api("PUT", f"{V2}/apis/{api_id}", {**full, "lifecycleState": "PUBLISHED"})
    try:
        api("POST", f"{V2}/apis/{api_id}/_start")
    except HttpError as e:
        if "already started" not in e.body.lower():
            raise
    sync_llm_model_prefix(api_id)
    api("POST", f"{V2}/apis/{api_id}/deployments", {"deploymentLabel": "nusantara-demo"})
    if models_synced:
        print(f"  ~ cloud-llms accepts Claude Code models (incl. claude-opus-5-5)")
    print(f"  ~ LLM policies synced on {name}")


def ensure_subscriptions(app_ids: dict[str, str]) -> None:
    subs_map = {
        "Nusantara Staff MCP": ["Nusantara Staff Agent"],
        "Nusantara Dev MCP": ["Nusantara Dev Agent"],
        "Nusantara LLM Gateway": ["Nusantara Staff Agent", "Nusantara Dev Agent"],
    }
    for api_name, apps in subs_map.items():
        a = api_by_name(api_name)
        if not a:
            continue
        plans = items(api("GET", f"{V2}/apis/{a['id']}/plans?perPage=20"))
        plan = next((p for p in plans if p.get("status") == "PUBLISHED"), None)
        if not plan:
            continue
        for app_name in apps:
            app_id = app_ids.get(app_name)
            if not app_id:
                continue
            existing = items(api("GET",
                f"{V2}/apis/{a['id']}/subscriptions?applicationIds={app_id}&statuses=ACCEPTED&statuses=PENDING"))
            if any(s.get("plan", {}).get("id") == plan["id"] or s.get("plan") == plan["id"] for s in existing):
                print(f"  = subscription {app_name} → {api_name}")
                continue
            try:
                sub = api("POST", f"{V2}/apis/{a['id']}/subscriptions", {"applicationId": app_id, "planId": plan["id"]})
            except HttpError as e:
                if "notSubscribable" in e.body or "keyless" in e.body.lower():
                    print(f"  = {api_name} keyless")
                    continue
                raise
            if sub.get("status") == "PENDING":
                api("POST", f"{V2}/apis/{a['id']}/subscriptions/{sub['id']}/_accept",
                    {"startingAt": None, "endingAt": None})
            print(f"  + subscription {app_name} → {api_name}")


def wait_mcp() -> None:
    import urllib.request
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8831/health", timeout=2) as r:
                if r.status == 200:
                    print("  policy MCP healthy")
                    return
        except Exception:
            pass
        time.sleep(1)
    sys.exit("nusantara-policy-mcp not reachable on :8831")


def main() -> None:
    print("Nusantara gateway provision")
    wait_mcp()
    app_ids = ensure_apps()
    ensure_mcp_proxy(
        "Nusantara Staff MCP", "/nusantara-staff-mcp", STAFF_TOOLS,
        "Staff composite — claims tools only; payout omitted upstream.",
    )
    ensure_mcp_proxy(
        "Nusantara Dev MCP", "/nusantara-dev-mcp", DEV_TOOLS,
        "Developer composite — repo tools + sandbox policy read; no payout.",
    )
    ensure_llm_gateway()
    if os.environ.get("NUSANTARA_SKIP_POLICY_GUARD") != "1":
        patch_staff_policy_guard()
    ensure_subscriptions(app_ids)
    print("\nGateway URLs (http://localhost:8082):")
    print("  LLM:   /nusantara-llm/chat/completions")
    print("  Staff: /nusantara-staff-mcp/mcp")
    print("  Dev:   /nusantara-dev-mcp/mcp")
    print("  UI:    http://localhost:8830")


if __name__ == "__main__":
    main()
