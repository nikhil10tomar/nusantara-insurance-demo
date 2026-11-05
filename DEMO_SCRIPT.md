# Charlie — custom demo for Mr. Agus (PT Asuransi Nusantara narrative)

**Prospect themes mapped:** developers on Claude Code + staff on public AI → **one AI Gateway**; OJK / **PDP Law** exposure → audit + PII; uncontrolled spend → **Budget-Wise**; controls → NIK & policy masking, domain block, prompt injection, **limited agent tools**.

**Before screen share**

- Open http://localhost:8830
- Open Gamma: http://gamma.localhost/environments/default/observe/traces (and **Logs** on **Nusantara LLM Gateway**)
- If health is red: `cd ~/working_directory/gamma-demo/nusantara-insurance-demo && ./setup.sh`

Demo password (AM): `NusantaraDemo#2026`

| Persona | User | Own policy |
|---------|------|------------|
| Claims staff | Siti Rahayu (`siti.claims`) | `POL-8842-001` |
| Developer | Agus Wijaya (`agus.dev`) | `POL-DEV-001` (sandbox) |

---

## 0. Frame the story (~1 min)

> “You told us developers use **Claude Code** on internal repos while staff experiment with **ChatGPT, Claude, and Gemini**. The risk isn’t the models — it’s **PDP Law** personal data like **NIK** and **policy numbers**, **OJK**-style auditability, shadow IT, prompt injection, and **AI spend** with no cap. We put **Gravitee AI Gateway** in front of every path: on-prem **Qwen** for regulated payloads, cloud models where appropriate, **MCP composites** so agents only see approved tools, and **Budget-Wise** on the LLM proxy.”

---

## 1. Staff — governed claims assistant (~2 min)

Tab **Claims staff**. Preset **Own policy + claims** → **Send**.

> “Staff never call Google or OpenAI directly. The assistant uses **delegated identity** (human `sub`, agent `act`) and a **composite MCP** — only `get_policy_status`, `list_claims`, `summarize_coverage`. **`initiate_payout` exists upstream but is not on the catalog** — same pattern as omitting dangerous tools for agents.”

Point at **Lineage**: AM password → token exchange → MCP → LLM.

---

## 2. PII — NIK & policy numbers (~1 min)

Preset **PII in chat (NIK)** → **Send**.

> “**PII filtering** on the LLM proxy scrubs identifiers before cloud models see them. In Gamma → **Nusantara LLM Gateway** → **Logs**, show masked payload — this is your **PDP Law** control point, not hope in the prompt.”

---

## 3. Prompt injection / cross-policy (~1 min)

Preset **Prompt injection (other policy)** as Siti (`POL-7711-002`).

> “The model might comply — Gravitee must not trust the prompt for authorization. Show **Gamma → Nusantara Staff MCP → plan → Own-policy boundary** (Groovy compares `preferred_username` to `policy_id`). On builds where the Groovy engine returns 403, you get a hard gateway deny; if your local gateway returns 500 on Groovy (same as Morrisons order boundary today), **narrate the 403 story** and point at the policy — production PDP/OJK control is the configured flow, not the model.”

To enable live boundary after `./setup.sh`: `python3 provision/gateway.py` **without** `NUSANTARA_SKIP_POLICY_GUARD=1`.

---

## 4. Developer — Claude Code path (~2 min)

Tab **Developer (Claude Code)**. Presets **Repo search** then **Read file via MCP**.

> “Developers get a **different composite MCP**: repo search and file read — no claims payout tools. Same gateway, different **tool surface** — how you limit what agents can access.”

Preset **Cross-policy (blocked)** for production `POL-8842-001`.

> “Even with repo access, **production policy data** is blocked at the MCP layer for the dev persona.”

---

## 5. Sidebar — models, shadow IT, injection, Budget-Wise (~3 min)

1. **Route to on-prem Qwen** — point at response header `X-Data-Residency: on-prem-id` (regulated path when NIK / POL in prompt).
2. **Cloud model (Gemini staff path)** — generic FAQ, no customer data.
3. **Shadow IT domain block** — show flow **Shadow IT domain block** on **Nusantara LLM Gateway** in Gamma; live prompt with `chatgpt.com` (if Groovy returns 500 locally, narrate **403 shadow-IT** — policy is in repo `provision/gateway.py` `DOMAIN_BLOCK`).
4. **Prompt injection phrase** — **Malicious Prompt Guard Rails** on the LLM proxy (show in Policy Studio; run preset and check logs).
5. **Budget-Wise burst** — repeat until **429** / Budget-Wise message.

> “**Budget-Wise** is the **monetary spend limit** policy — daily USD cap per client/team. FinOps sees the same analytics as security sees PII blocks.”

---

## 6. Close (~1 min)

> “Mr. Agus’s checklist: **PII masking**, **domain-based blocking**, **prompt injection protection**, **agent tool limits**, **Qwen on-prem + cloud models**, and **spend control** — all on the gateway you already run for APIs. Next step is connecting your real IdP and model endpoints; the policies transfer.”

---

## URLs

| What | URL |
|------|-----|
| Control tower | http://localhost:8830 |
| LLM proxy | http://localhost:8082/nusantara-llm/ |
| Staff MCP | http://localhost:8082/nusantara-staff-mcp/ |
| Dev MCP | http://localhost:8082/nusantara-dev-mcp/ |
| Gamma | http://gamma.localhost |
