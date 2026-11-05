#!/usr/bin/env python3
"""Point Nusantara LLM Gateway cloud endpoint at real Anthropic (same key as APIM «Claude» API).

Policies (PII, Budget-Wise, prompt guard, routing) stay on Nusantara LLM Gateway; only the
upstream changes from mock → api.anthropic.com. Idempotent.
"""
from __future__ import annotations

import copy
import json
import sys

from _http import basic, call, items

import os

APIM = os.environ.get("APIM_URL", "http://localhost:8083")
V2 = f"{APIM}/management/v2/environments/DEFAULT"
AUTH = basic("admin", "admin")
LLM_NAME = "Nusantara LLM Gateway"
SOURCE_NAME = "Claude"
CLOUD_EP = "cloud-llms"

EXTRA_MODELS = [
    {"name": "claude-opus-5-5", "inputPrice": 15.0, "outputPrice": 75.0, "aliases": []},
    {"name": "claude-opus-4-8", "inputPrice": 15.0, "outputPrice": 75.0, "aliases": []},
    {"name": "claude-sonnet-4-6", "inputPrice": 3.0, "outputPrice": 15.0, "aliases": []},
    {"name": "claude-opus-4-6", "inputPrice": 15.0, "outputPrice": 75.0, "aliases": []},
    {"name": "claude-haiku-4-5", "inputPrice": 0.8, "outputPrice": 4.0, "aliases": []},
]


def api(method: str, url: str, body=None):
    return call(method, url, body, auth=AUTH, timeout=120)


def api_by_name(name: str) -> dict | None:
    return next((a for a in items(api("GET", f"{V2}/apis?perPage=300")) if a.get("name") == name), None)


def main() -> None:
    source = api_by_name(SOURCE_NAME)
    if not source:
        sys.exit(f"APIM API «{SOURCE_NAME}» not found — add Anthropic key there first, or keep mock upstream.")
    target = api_by_name(LLM_NAME)
    if not target:
        sys.exit(f"«{LLM_NAME}» not found — run ./setup.sh first.")

    src_full = api("GET", f"{V2}/apis/{source['id']}")
    src_ep = src_full["endpointGroups"][0]["endpoints"][0]
    src_cfg = src_ep["configuration"]
    if isinstance(src_cfg, str):
        src_cfg = json.loads(src_cfg)

    full = api("GET", f"{V2}/apis/{target['id']}")
    changed = False
    for group in full.get("endpointGroups") or []:
        for ep in group.get("endpoints") or []:
            if ep.get("name") != CLOUD_EP:
                continue
            cfg = ep.get("configuration") or {}
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            cfg["provider"] = src_cfg.get("provider", "ANTHROPIC")
            cfg["target"] = src_cfg.get("target", "https://api.anthropic.com")
            cfg["authentication"] = copy.deepcopy(src_cfg.get("authentication") or {})
            by_name = {m["name"]: m for m in cfg.get("models") or []}
            for m in EXTRA_MODELS:
                by_name.setdefault(m["name"], m)
            cfg["models"] = list(by_name.values())
            cfg["modelGovernance"] = {
                "prefixPolicy": {"policy": "NO_PREFIX"},
                "aliasOnly": False,
                "modelPattern": "",
            }
            ep["configuration"] = cfg
            changed = True
            print(f"  ~ {CLOUD_EP} → {cfg['target']} ({cfg['provider']})")

    if not changed:
        sys.exit(f"Endpoint «{CLOUD_EP}» not found on {LLM_NAME}")

    for k in ("id", "crossId", "hrid", "deployedAt", "createdAt", "updatedAt", "state",
              "deploymentState", "lifecycleState", "primaryOwner", "workflowState",
              "disableMembershipNotifications", "originContext", "definitionContext"):
        full.pop(k, None)
    api("PUT", f"{V2}/apis/{target['id']}", full)
    api("POST", f"{V2}/apis/{target['id']}/deployments", {"deploymentLabel": "claude-cli-upstream"})
    print(f"Deployed. Claude CLI → http://localhost:8082/nusantara-llm/ (policies on {LLM_NAME})")


if __name__ == "__main__":
    main()
