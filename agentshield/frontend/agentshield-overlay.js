(function () {
  if (window.__agentShieldLoaded) return;
  window.__agentShieldLoaded = true;

  const config = Object.assign(
    {
      apiBaseUrl: "http://127.0.0.1:8000",
      zIndex: 2147483640,
      title: "AgentShield",
      sessionId: "default",
      eventsPollMs: 1500,
    },
    window.AgentShieldConfig || {}
  );
  let lastEventSeq = 0;
  let eventsTimer = null;

  const style = document.createElement("style");
  style.textContent = `
    .as-launcher {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: ${config.zIndex};
      border: none;
      border-radius: 999px;
      background: #111827;
      color: #fff;
      font: 600 14px/1.2 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      padding: 12px 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,.25);
      cursor: pointer;
    }
    .as-panel {
      position: fixed;
      right: 20px;
      bottom: 72px;
      width: min(420px, calc(100vw - 32px));
      max-height: 78vh;
      overflow: auto;
      z-index: ${config.zIndex};
      border-radius: 16px;
      border: 1px solid #d1d5db;
      background: rgba(255,255,255,.98);
      backdrop-filter: blur(8px);
      box-shadow: 0 16px 50px rgba(0,0,0,.22);
      padding: 14px;
      font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      color: #0f172a;
      display: none;
    }
    .as-panel.open { display: block; }
    .as-head {
      display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
    }
    .as-title { font-weight: 800; font-size: 14px; }
    .as-close {
      border: none; background: transparent; cursor: pointer; font-size: 16px; color: #334155;
    }
    .as-grid { display: grid; gap: 8px; }
    .as-label { font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: #475569; font-weight: 700; }
    .as-input, .as-select, .as-textarea {
      width: 100%;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      padding: 8px 10px;
      font: inherit;
      color: inherit;
      background: #fff;
      box-sizing: border-box;
    }
    .as-textarea { min-height: 64px; resize: vertical; }
    .as-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .as-btn {
      width: 100%; border: none; border-radius: 10px; padding: 10px 12px;
      background: #0f172a; color: #fff; cursor: pointer; font-weight: 700;
    }
    .as-card {
      border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px; background: #f8fafc;
    }
    .as-badge {
      display: inline-block; padding: 3px 8px; border-radius: 999px;
      font-size: 11px; font-weight: 700; margin-left: 6px;
    }
    .as-ok { background: #dcfce7; color: #166534; }
    .as-warn { background: #fef3c7; color: #92400e; }
    .as-risk { background: #fee2e2; color: #991b1b; }
    .as-list { margin: 6px 0 0; padding-left: 18px; }
    .as-mini-btn {
      border: 1px solid #cbd5e1;
      background: #fff;
      color: #0f172a;
      border-radius: 8px;
      padding: 6px 8px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
    }
    .as-pending-item { border-top: 1px solid #e2e8f0; padding-top: 8px; margin-top: 8px; }
    .as-actions { display: flex; gap: 6px; margin-top: 6px; }
    .as-event-item { border-top: 1px solid #e2e8f0; padding-top: 8px; margin-top: 8px; font-size: 12px; }
    .as-event-meta { color: #64748b; font-size: 11px; }
    .as-toast {
      position: fixed; right: 20px; top: 20px; z-index: ${config.zIndex};
      background: #111827; color: #fff; border-radius: 10px; padding: 10px 12px;
      font: 12px/1.3 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      box-shadow: 0 10px 30px rgba(0,0,0,.25);
      opacity: 0; transform: translateY(-4px); transition: .2s ease;
      pointer-events: none;
    }
    .as-toast.show { opacity: 1; transform: translateY(0); }
  `;
  document.head.appendChild(style);

  const launcher = document.createElement("button");
  launcher.className = "as-launcher";
  launcher.textContent = "Open AgentShield";

  const panel = document.createElement("aside");
  panel.className = "as-panel";
  panel.innerHTML = `
    <div class="as-head">
      <div class="as-title">${config.title} Control Panel</div>
      <button class="as-close" aria-label="Close">✕</button>
    </div>

    <div class="as-grid">
      <div class="as-card" id="as-latest-action">
        <strong>Latest Proposed Action</strong>
        <div style="font-size:12px;color:#334155;margin-top:6px;">No action proposed yet.</div>
      </div>
      <div class="as-card" id="as-current-assessment">
        <strong>Current Assessment</strong>
        <div style="font-size:12px;color:#334155;margin-top:6px;">No live assessment yet.</div>
      </div>
      <div class="as-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>Pending Human Gates</strong>
          <button class="as-mini-btn" id="as-refresh-pending">Refresh</button>
        </div>
        <div id="as-pending-list" style="font-size:12px;color:#334155;margin-top:6px;">No pending actions.</div>
      </div>
      <div class="as-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>Live Agent Activity</strong>
          <button class="as-mini-btn" id="as-refresh-events">Refresh</button>
        </div>
        <div id="as-events-list" style="font-size:12px;color:#334155;margin-top:6px;">No activity yet.</div>
      </div>
    </div>
  `;

  const toast = document.createElement("div");
  toast.className = "as-toast";

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function openPanel() {
    panel.classList.add("open");
    loadPendingGates();
    loadEvents();
    if (!eventsTimer) {
      eventsTimer = setInterval(loadEvents, config.eventsPollMs);
    }
  }
  function closePanel() {
    panel.classList.remove("open");
    if (eventsTimer) {
      clearInterval(eventsTimer);
      eventsTimer = null;
    }
  }

  async function loadPendingGates() {
    const list = panel.querySelector("#as-pending-list");
    try {
      const params = new URLSearchParams({ session_id: String(config.sessionId) });
      const response = await fetch(`${config.apiBaseUrl}/api/v1/gates/pending?${params.toString()}`);
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const items = await response.json();
      if (!items.length) {
        list.textContent = "No pending actions.";
        return;
      }
      list.innerHTML = items
        .slice(0, 6)
        .map(
          (item) => `
          <div class="as-pending-item">
            <div><strong>${item.action.action_type}</strong> - ${item.action.description}</div>
            <div style="color:#64748b;">${item.reason}</div>
            <div class="as-actions">
              <button class="as-mini-btn" data-gate-id="${item.gate_id}" data-decision="approve">Approve</button>
              <button class="as-mini-btn" data-gate-id="${item.gate_id}" data-decision="reject">Reject</button>
            </div>
          </div>
        `
        )
        .join("");
    } catch (err) {
      list.textContent = `Failed to load pending gates: ${String(err.message || err)}`;
    }
  }

  async function loadEvents() {
    const list = panel.querySelector("#as-events-list");
    const assessment = panel.querySelector("#as-current-assessment");
    const latestAction = panel.querySelector("#as-latest-action");
    try {
      const params = new URLSearchParams({
        session_id: String(config.sessionId),
        after_seq: String(lastEventSeq),
        limit: "20",
      });
      const response = await fetch(`${config.apiBaseUrl}/api/v1/events?${params.toString()}`);
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const payload = await response.json();
      const events = payload.events || [];
      lastEventSeq = payload.last_seq || lastEventSeq;
      if (!events.length && !list.getAttribute("data-has-events")) {
        list.textContent = "No activity yet.";
        return;
      }

      if (events.length) {
        if (events.some((evt) => evt.event_type === "gate.proposed" || evt.event_type === "gate.decision")) {
          loadPendingGates();
        }
        const proposed = [...events].reverse().find((evt) => evt.event_type === "action.proposed");
        if (proposed) {
          const action = (proposed.data || {}).action || {};
          latestAction.innerHTML = `
            <strong>Latest Proposed Action</strong>
            <div style="margin-top:6px;font-size:12px;color:#334155;">
              <div><strong>Type:</strong> ${action.action_type || "-"}</div>
              <div><strong>Description:</strong> ${action.description || "-"}</div>
              <div><strong>Command:</strong> ${action.command || "-"}</div>
              <div><strong>Target:</strong> ${action.target_path || "-"}</div>
            </div>
          `;
        }
        const evaluated = [...events].reverse().find((evt) => evt.event_type === "action.evaluated");
        if (evaluated) {
          const d = evaluated.data || {};
          const gateClass =
            d.gate === "auto_execute" ? "as-ok" : d.gate === "log_and_execute" ? "as-warn" : "as-risk";
          assessment.innerHTML = `
            <strong>Current Assessment</strong>
            <div style="margin-top:6px;">
              <div><strong>Gate:</strong> <span class="as-badge ${gateClass}">${d.gate || "unknown"}</span></div>
              <div><strong>Reversibility:</strong> ${typeof d.score === "number" ? d.score.toFixed(2) : d.score || "-"}</div>
              <div><strong>Operation:</strong> ${d.operation || "-"}</div>
              <div><strong>Classifier:</strong> ${d.classifier || "-"}</div>
              <div><strong>Blast Radius:</strong> ${d.blast_summary || "-"}</div>
            </div>
          `;
        }

        const oldHtml = list.innerHTML === "No activity yet." ? "" : list.innerHTML;
        const newHtml = events
          .slice(-10)
          .map((event) => {
            const ts = new Date(event.timestamp * 1000).toLocaleTimeString();
            const level = event.level === "warn" ? "WARN" : event.level === "error" ? "ERROR" : "INFO";
            return `
              <div class="as-event-item">
                <div><strong>[${level}]</strong> ${event.message}</div>
                <div class="as-event-meta">${ts} • ${event.event_type}</div>
              </div>
            `;
          })
          .join("");
        list.innerHTML = `${newHtml}${oldHtml}`;
        list.setAttribute("data-has-events", "1");
      }
    } catch (err) {
      list.textContent = `Failed to load events: ${String(err.message || err)}`;
    }
  }

  async function decideGate(gateId, decision) {
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/v1/gates/${gateId}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      showToast(`Gate ${decision}d.`);
      await loadPendingGates();
    } catch (err) {
      showToast(`Failed: ${String(err.message || err)}`);
    }
  }

  launcher.addEventListener("click", openPanel);
  panel.querySelector(".as-close").addEventListener("click", closePanel);
  panel.querySelector("#as-refresh-pending").addEventListener("click", loadPendingGates);
  panel.querySelector("#as-refresh-events").addEventListener("click", loadEvents);
  panel.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const gateId = target.getAttribute("data-gate-id");
    const decision = target.getAttribute("data-decision");
    if (gateId && decision) {
      decideGate(gateId, decision);
    }
  });

  document.body.appendChild(launcher);
  document.body.appendChild(panel);
  document.body.appendChild(toast);

  window.AgentShieldOverlay = {
    open: openPanel,
    close: closePanel,
    loadPendingGates,
    loadEvents,
  };
})();
