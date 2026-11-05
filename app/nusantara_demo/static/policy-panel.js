/** Shared live policy cockpit (browser Claude + optional main UI). */
export function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

export function renderPolicyPanel(container, cockpit) {
  if (!container || !cockpit) return;
  const g = cockpit.gamma || {};
  let html = `<div class="policy-tx"><strong>Gravitee transaction</strong> <code>${esc(cockpit.transaction_id || "—")}</code></div>`;
  html += `<div class="policy-links">`;
  html += `<a href="${esc(g.gamma_logs || "#")}" target="_blank" rel="noopener">Gamma → Logs</a> · `;
  html += `<a href="${esc(g.gamma_traces || "#")}" target="_blank" rel="noopener">Traces</a> · `;
  html += `<a href="${esc(g.gamma_apis || "#")}" target="_blank" rel="noopener">APIs / Policy Studio</a>`;
  html += `</div><p class="policy-hint">${esc(g.gamma_hint || "")}</p>`;

  const section = (title, items, cls) => {
    if (!items?.length) return "";
    let s = `<h3 class="policy-section ${cls}">${esc(title)}</h3><ul class="policy-list">`;
    for (const p of items) {
      s += `<li><span class="policy-name">${esc(p.name)}</span>`;
      if (p.detail) s += `<span class="policy-detail">${esc(p.detail)}</span>`;
      s += `</li>`;
    }
    return s + `</ul>`;
  };

  html += section("Applied on this request", cockpit.applied, "applied");
  html += section("Blocked", cockpit.blocked, "blocked");
  html += section("Always on (show in Policy Studio)", cockpit.watch, "watch");

  html += `<details class="policy-catalog"><summary>All policies on ${esc("Nusantara LLM Gateway")}</summary><ul>`;
  for (const c of cockpit.catalog || []) {
    html += `<li><code>${esc(c.policy)}</code> — ${esc(c.name)}</li>`;
  }
  html += `</ul><p class="policy-hint">${esc(g.policy_studio_hint || "")}</p></details>`;

  container.innerHTML = html;
}
