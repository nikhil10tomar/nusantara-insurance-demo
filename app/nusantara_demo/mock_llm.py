"""OpenAI-compatible LLM stand-ins: on-prem Qwen + cloud Claude/GPT/Gemini."""
from __future__ import annotations

import json
import os
import re
import time
import uuid

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ROLE = os.environ.get("MOCK_LLM_ROLE", "qwen")  # qwen | cloud


def _usage(prompt: str, answer: str) -> dict:
    return {
        "prompt_tokens": max(24, len(prompt) // 3),
        "completion_tokens": max(16, len(answer) // 3),
        "total_tokens": max(40, (len(prompt) + len(answer)) // 3),
    }


def _user_text(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _pick_answer(messages: list, model: str) -> tuple[str, str]:
    user = _user_text(messages)
    lower = user.lower()
    routed = model or ("qwen2.5-7b-instruct" if ROLE == "qwen" else "claude-sonnet-4-6")
    if ROLE == "qwen":
        return (
            f"[On-prem Qwen] Governed summary for regulated data path: {user[:160] or 'hello'} "
            "(PDP Law — processing stays in your VPC).",
            routed,
        )
    if "gpt" in routed.lower():
        return (f"[Cloud OpenAI] Staff assistant: {user[:140] or 'hello'}", routed)
    if "gemini" in routed.lower():
        return (f"[Cloud Gemini] Staff assistant: {user[:140] or 'hello'}", routed)
    return (f"[Cloud Claude] Developer / staff path: {user[:140] or 'hello'}", routed)


def _maybe_tool_calls(user: str, tools: list | None, messages: list) -> list | None:
    if not tools:
        return None
    if any(m.get("role") == "tool" for m in messages):
        return None
    lower = user.lower()
    m = re.search(r"POL-[0-9]{4}-[0-9]{3}", user, re.I)
    if m and any(k in lower for k in ("policy", "claim", "coverage", "status", "nik")):
        name = "list_claims_for_policy" if "claim" in lower else "get_policy_status"
        if "coverage" in lower or "summary" in lower:
            name = "summarize_coverage"
        return [{
            "id": "call_nus_1",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps({"policy_id": m.group(0).upper()})},
        }]
    if any(k in lower for k in ("repo", "code", "openapi", "readme", "claude code")):
        if "file" in lower or "openapi" in lower:
            return [{
                "id": "call_dev_1",
                "type": "function",
                "function": {
                    "name": "get_repo_file",
                    "arguments": json.dumps({"path": "claims-api/openapi.yaml"}),
                },
            }]
        return [{
            "id": "call_dev_2",
            "type": "function",
            "function": {"name": "search_codebase", "arguments": json.dumps({"query": user[:80]})},
        }]
    return None


async def chat_completions(request: Request) -> Response:
    body = await request.json()
    model = body.get("model") or ("qwen2.5-7b-instruct" if ROLE == "qwen" else "claude-sonnet-4-6")
    messages = body.get("messages") or []
    user = _user_text(messages)
    tool_calls = _maybe_tool_calls(user, body.get("tools"), messages)
    if tool_calls:
        answer = None
        routed = model
    else:
        answer, routed = _pick_answer(messages, model)
    usage = _usage(json.dumps(messages)[:800], answer or "tool_call")
    payload = {
        "id": f"chatcmpl-nus-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": (
                {"role": "assistant", "content": answer, "tool_calls": tool_calls}
                if tool_calls
                else {"role": "assistant", "content": answer}
            ),
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": usage,
    }
    headers = {
        "X-Nusantara-Mock-Role": ROLE,
        "X-Gravitee-Routed-Model": routed,
        "X-Data-Residency": "on-prem-id" if ROLE == "qwen" else "cloud",
    }
    return JSONResponse(payload, headers=headers)


async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "role": ROLE})


async def models(_request: Request) -> Response:
    if ROLE == "qwen":
        data = [{"id": "qwen2.5-7b-instruct", "object": "model"}]
    else:
        data = [
            {"id": "claude-opus-5-5", "object": "model"},
            {"id": "claude-opus-4-8", "object": "model"},
            {"id": "claude-opus-4-6", "object": "model"},
            {"id": "claude-sonnet-4-6", "object": "model"},
            {"id": "claude-haiku-4-5", "object": "model"},
            {"id": "gpt-4o", "object": "model"},
            {"id": "gemini-2.0-flash", "object": "model"},
        ]
    return JSONResponse({"object": "list", "data": data})


app = Starlette(routes=[
    Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    Route("/v1/models", models, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
])


def main() -> None:
    port = int(os.environ.get("PORT", "8832"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
