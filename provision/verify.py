#!/usr/bin/env python3
"""Quick smoke test after setup."""
from __future__ import annotations

import json
import urllib.request

GW = "http://localhost:8082"
UI = "http://localhost:8830"


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.status, r.read().decode()[:400]
    except Exception as e:
        return 0, str(e)


def main() -> None:
    ok = True
    for name, url in [
        ("UI health", f"{UI}/api/health"),
        ("Policy MCP", "http://localhost:8831/health"),
        ("LLM gateway", f"{GW}/nusantara-llm/v1/models"),
    ]:
        status, body = get(url)
        good = 200 <= status < 500
        print(f"{'OK' if good else 'FAIL'} {name}: {status} {body[:120]}")
        ok = ok and good
    r = urllib.request.Request(
        f"{GW}/nusantara-llm/chat/completions",
        data=json.dumps({
            "model": "gemini-2.0-flash",
            "messages": [{"role": "user", "content": "Hello"}],
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            print(f"OK LLM chat: {resp.status}")
    except Exception as e:
        print(f"FAIL LLM chat: {e}")
        ok = False
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
