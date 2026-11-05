# Claude in the browser + live policies

Your **existing** demo (control tower, gateway, MCP, `./setup.sh`) is unchanged. This adds a second UI that talks to the same **Nusantara LLM Gateway** and shows **which policies applied** on each message.

## Open

1. **Chat + policy panel (recommended):** http://localhost:8830/claude  
2. **Gamma (second tab / monitor):** http://gamma.localhost/environments/default/observe/logs — filter API **Nusantara LLM Gateway**, paste **Gravitee transaction id** from the right-hand panel.

From the main control tower: **Claude in browser + policies** (header link).

## Presenter layout

| Left | Right |
|------|--------|
| http://localhost:8830/claude | Policy panel (auto-updates) |
| Optional 3rd tab | Gamma Logs with same transaction id |

Presets on `/claude` mirror the demo: NIK/Qwen, shadow IT, prompt injection.

## Not claude.ai

Consumer **claude.ai** cannot be routed through your local gateway without enterprise proxy/DNS. For the prospect demo, use **`/claude`** (governed path) beside Gamma — same policies as Claude Code hitting `/nusantara-llm`.

## Optional: Claude Code CLI (same gateway)

```bash
cd ~/working_directory/gamma-demo/nusantara-insurance-demo
eval "$(python3 provision/claude_env.py)"
claude -p --model claude-sonnet-4-6 "Hello via gateway"
```

Then show Gamma logs for that traffic (same API as the browser page).

## Refresh after code changes

Static files are volume-mounted; restart the tower:

```bash
docker compose restart nusantara-control-tower
```

If you changed Python (`tower.py`, `policy_cockpit.py`):

```bash
docker compose build nusantara-control-tower && docker compose up -d nusantara-control-tower
```
