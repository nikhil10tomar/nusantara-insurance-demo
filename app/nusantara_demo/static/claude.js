import { esc, renderPolicyPanel } from "/static/policy-panel.js";

const logEl = document.getElementById("log");
const policyEl = document.getElementById("policy-panel");
const modelEl = document.getElementById("model");

function log(role, text) {
  const d = document.createElement("div");
  d.className = `msg ${role}`;
  d.innerHTML = `<strong>${esc(role)}:</strong> ${esc(text)}`;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

document.querySelectorAll(".presets [data-msg]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.getElementById("message").value = btn.dataset.msg;
  });
});

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = document.getElementById("message").value.trim();
  if (!message) return;
  const model = modelEl.value;
  log("you", message);
  document.getElementById("message").value = "";
  policyEl.innerHTML = "<p class='policy-hint'>Waiting for gateway…</p>";

  const r = await fetch("/api/claude/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, model }),
  });
  const data = await r.json();
  const text =
    data.assistant_text ||
    (data.body?.error?.message ? `Gateway: ${data.body.error.message}` : JSON.stringify(data.body).slice(0, 400));
  log("claude", text);
  renderPolicyPanel(policyEl, data.cockpit);
});

log("system", "Chat uses /nusantara-llm on your local gateway (same policies as the demo).");
