#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose build nusantara-control-tower
docker compose up -d --force-recreate
python3 provision/am.py
sleep 8
# Groovy own-policy boundary may 500 on some local gateway builds (same as Morrisons demo); skip for live chat.
NUSANTARA_SKIP_POLICY_GUARD=1 python3 provision/gateway.py

for i in $(seq 1 30); do
  curl -sf http://localhost:8830/api/health >/dev/null && break
  sleep 2
done
curl -s -X POST http://localhost:8831/reset >/dev/null || true
echo ""
echo "Nusantara demo ready: http://localhost:8830"
echo "Gamma: http://gamma.localhost/environments/default/observe/traces"
echo "Script: DEMO_SCRIPT.md"
