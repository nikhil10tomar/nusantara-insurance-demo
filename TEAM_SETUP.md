# Clone and run Nusantara locally (for anyone on the team)

This repo is **not** a full self-contained Gravitee stack. It builds **on top of** your team’s local Gamma / APIM / Access Management (same baseline Gravitee uses for other demos). You still get a repeatable demo from git: one script provisions APIs, plans, and mock app containers.

## What you need installed

- **Docker** (with Compose)
- **Python 3.10+** (stdlib only for `provision/` — no `pip install` required for scripts)
- **curl**
- **Git**
- Optional for real Claude answers: **Claude Code** / `claude` CLI ([Anthropic](https://www.anthropic.com/claude-code))

## 1. Start the Gravitee “platform” first

Bring up whatever your org uses for **local Gamma** (typical layout):

| Service            | Typical host port | Notes                                      |
|--------------------|-------------------|--------------------------------------------|
| API Gateway        | `8082`            | HTTP traffic to LLM / MCP paths            |
| APIM (management)  | `8083`            | Where `provision/*.py` talk to             |
| Access Management  | `8092` / `8093`   | OAuth / token exchange domain `gamma`      |

**Networking:** the demo’s `docker-compose.yml` expects an **external** Docker network named **`docker_default`**. Your Gamma stack usually creates this; if not:

```bash
docker network create docker_default
```

**Gamma UI (presenter):** [http://gamma.localhost](http://gamma.localhost) — add `127.0.0.1 gamma.localhost` to `/etc/hosts` if needed.

### gamma-next (alternative ports)

If your gateway is **8182** and APIM **8183**, set these whenever you run setup scripts:

```bash
export APIM_URL=http://localhost:8183
export GATEWAY_URL=http://localhost:8182
export GATEWAY_LLM_URL=http://localhost:8182/nusantara-llm
```

Then run `./setup.sh` and `./setup-claude-cli.sh` with those env vars in the same shell.

## 2. One-time APIM requirement: **ACME Hotels LLMs**

`provision/gateway.py` **clones** policy flows from an existing APIM API named **`ACME Hotels LLMs`**. That API must exist in your **DEFAULT** environment before `./setup.sh` can create **Nusantara LLM Gateway**.

If your bootstrap does not include it:

- Import it from the Gravitee **acme-hotel-gamma** pack / JSON your team uses, **or**
- Copy another working **LLM proxy** API and rename it to **`ACME Hotels LLMs`** with compatible LLM proxy flows (advanced).

Until that exists, `gateway.py` will exit with an error pointing at the missing API.

Optional: add a **Claude** LLM API in APIM with a valid Anthropic key so `./setup-claude-cli.sh` → `wire_claude_upstream.py` can point the cloud endpoint at `api.anthropic.com`.

## 3. Clone and install this demo

```bash
git clone https://github.com/<org-or-user>/nusantara-insurance-demo.git
cd nusantara-insurance-demo
chmod +x setup.sh setup-claude-cli.sh
./setup.sh
```

What `./setup.sh` does:

- Builds and starts **control tower** (:8830), **policy MCP** (:8831), **mock Qwen** (:8832), **mock cloud** (:8833) on `docker_default`
- Runs **`provision/am.py`** (users / apps in AM domain `gamma`)
- Runs **`provision/gateway.py`** (Nusantara LLM Gateway, MCP proxies, subscriptions)

Open **http://localhost:8830** and follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## 4. Verify

```bash
python3 provision/verify.py
```

Expect UI and gateway checks to pass. (The script may hit `/v1/models`; if your build returns “not implemented” for that path but chat works, treat chat as the source of truth.)

## 5. Optional: Claude Code through the gateway

```bash
./setup-claude-cli.sh
eval "$(python3 provision/claude_env.py)"
claude
```

Developer audit story (delegated token):

```bash
eval "$(python3 provision/claude_env.py --delegated)"
claude
```

Details: [CLI_CLAUDE.md](CLI_CLAUDE.md)

## Demo accounts (AM)

Password for all demo users: **`NusantaraDemo#2026`**

| Persona       | Username     | Own policy    |
|---------------|--------------|---------------|
| Claims staff  | `siti.claims`| `POL-8842-001` |
| Developer     | `agus.dev`   | `POL-DEV-001`  |

## Troubleshooting (short)

| Symptom | What to do |
|--------|------------|
| `ACME Hotels LLMs` required | Import or create that API in APIM, then re-run `python3 provision/gateway.py` |
| Network / compose errors | Ensure **`docker_default`** exists and Gamma containers are up |
| Wrong ports | Set `APIM_URL`, `GATEWAY_URL`, `GATEWAY_LLM_URL` (see above) |
| Claude: model does not exist | Run `python3 provision/gateway.py` again (refreshes model list on the proxy) |
| 401 on delegated CLI | Re-run `eval "$(python3 provision/claude_env.py --delegated)"` |

## What *not* to commit

Never commit `.env`, license keys, or real API keys. Use APIM UI or env for secrets.
