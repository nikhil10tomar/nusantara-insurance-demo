#!/usr/bin/env bash
# Claude Code CLI → Gravitee Nusantara LLM Gateway (policies on the proxy).
set -euo pipefail
cd "$(dirname "$0")"

APIM_URL="${APIM_URL:-http://localhost:8083}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8082}"

if ! curl -sf "${APIM_URL}/management/organizations/DEFAULT/environments/DEFAULT" -u admin:admin >/dev/null; then
  echo "APIM not reachable at ${APIM_URL} — start local Gamma first."
  echo "If you use gamma-next, try: APIM_URL=http://localhost:8183 GATEWAY_URL=http://localhost:8182 ./setup-claude-cli.sh"
  exit 1
fi

if ! APIM_URL="${APIM_URL}" python3 - <<'PY'
import os, sys
from provision._http import basic, call, items

apim = os.environ["APIM_URL"]
apis = items(call("GET", f"{apim}/management/v2/environments/DEFAULT/apis?perPage=300", auth=basic("admin", "admin")))
names = {a.get("name") for a in apis}
if "Nusantara LLM Gateway" not in names:
    print("Nusantara LLM Gateway not in APIM — run ./setup.sh first.", file=sys.stderr)
    if names:
        print("Hint: if APIs exist on another port, re-run with APIM_URL=...", file=sys.stderr)
    sys.exit(1)
PY
then
  exit 1
fi

# LLM proxy root often returns 404/405; that still means the gateway is up.
gw_code=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/nusantara-llm/" || echo "000")
if [[ "${gw_code}" == "000" ]]; then
  echo "Gateway not reachable at ${GATEWAY_URL} — check GATEWAY_URL."
  exit 1
fi
echo "Gateway OK (${GATEWAY_URL}/nusantara-llm/ → HTTP ${gw_code})"

export APIM_URL GATEWAY_URL
export GATEWAY_LLM_URL="${GATEWAY_URL}/nusantara-llm"

echo "== Wire cloud endpoint to Anthropic (via existing APIM «Claude» API key) =="
python3 provision/wire_claude_upstream.py || echo "(wire skipped — using mock cloud upstream)"

echo ""
echo "== Gateway smoke test =="
python3 provision/claude_env.py --check || true

echo ""
cat <<'EOF'
== Claude CLI (policies apply on every message) ==

  cd ~/working_directory/gamma-demo/nusantara-insurance-demo
  export GATEWAY_LLM_URL=http://localhost:8082/nusantara-llm   # or 8182 if gamma-next
  eval "$(python3 provision/claude_env.py)"
  claude

Developer identity (OBO, for Gamma audit):

  eval "$(python3 provision/claude_env.py --delegated)"
  claude

While you chat, open Gamma → Observe → Logs → API «Nusantara LLM Gateway».
See CLI_CLAUDE.md for demo prompts (PII, Qwen route, Budget-Wise).

EOF
