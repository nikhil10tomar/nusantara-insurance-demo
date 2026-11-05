"""Tiny stdlib HTTP helpers shared by the provisioning scripts (no extra deps)."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class HttpError(RuntimeError):
    def __init__(self, method: str, url: str, code: int, body: str):
        super().__init__(f"{method} {url} -> {code}: {body[:600]}")
        self.code = code
        self.body = body


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def call(method: str, url: str, body: Any = None, *, auth: str | None = None,
         form: dict | None = None, timeout: int = 60) -> Any:
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw.decode()
    except urllib.error.HTTPError as e:
        raise HttpError(method, url, e.code, e.read().decode("utf-8", "replace")) from e


def items(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    for key in ("data", "content", "items"):
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return payload[key]
    return []


def jwt_claims(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))
