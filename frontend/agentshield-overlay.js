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
    @import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
    .as-launcher {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: ${config.zIndex};
      border: 1px solid rgba(0, 0, 0, 0.1);
      border-radius: 8px;
      background: linear-gradient(135deg, #ffffff, #f0f0f5);
      color: #111111;
      font: 500 13px/1.2 'Geist', system-ui, -apple-system, sans-serif;
      padding: 12px 20px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.3), 0 0 15px rgba(0,0,0,0.05);
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .as-launcher:hover { background: #ffffff; border-color: rgba(0, 0, 0, 0.2); transform: translateY(-2px); box-shadow: 0 14px 40px rgba(0,0,0,0.4); }
    .as-panel {
      position: fixed;
      right: 20px;
      bottom: 72px;
      width: min(420px, calc(100vw - 32px));
      max-height: 78vh;
      overflow: auto;
      z-index: ${config.zIndex};
      border-radius: 12px;
      border: 1px solid rgba(0, 0, 0, 0.15);
      background: rgba(255, 255, 255, 0.95);
      backdrop-filter: blur(24px) saturate(180%);
      -webkit-backdrop-filter: blur(24px) saturate(180%);
      box-shadow: 0 30px 100px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,1);
      padding: 18px;
      font: 13px/1.45 'Geist', system-ui, -apple-system, sans-serif;
      color: #111111;
      display: none;
      transition: opacity 0.2s, transform 0.2s;
    }
    .as-panel.open { display: block; }
    .as-head {
      display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
    }
    .as-title { font-weight: 600; font-size: 14px; letter-spacing: -0.01em; color: #000; }
    .as-close {
      border: none; background: transparent; cursor: pointer; font-size: 16px; color: #666;
      transition: color 0.2s;
    }
    .as-close:hover { color: #000; }
    .as-grid { display: grid; gap: 12px; }
    .as-label { font-size: 11px; font-family: 'JetBrains Mono', monospace; letter-spacing: .05em; text-transform: uppercase; color: #555; font-weight: 400; }
    .as-input, .as-select, .as-textarea {
      width: 100%;
      border: 1px solid #ccc;
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      color: #111;
      background: #fafafa;
      box-sizing: border-box;
      transition: border-color 0.2s;
    }
    .as-input:focus, .as-select:focus, .as-textarea:focus { border-color: #333; outline: none; }
    .as-textarea { min-height: 64px; resize: vertical; }
    .as-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .as-btn {
      width: 100%; border: 1px solid #222; border-radius: 6px; padding: 10px 12px;
      background: #111; color: #fff; cursor: pointer; font-weight: 500; transition: all 0.2s;
    }
    .as-btn:hover { background: #333; }
    .as-card {
      border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; padding: 14px; background: rgba(250,250,250,0.8);
      box-shadow: 0 2px 8px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,0.8);
    }
    .as-card strong { font-weight: 600; color: #222; }
    .as-badge {
      display: inline-block; padding: 3px 6px; border-radius: 4px;
      font-size: 11px; font-family: 'JetBrains Mono', monospace; font-weight: 500; margin-left: 6px;
    }
    .as-ok { background: rgba(16, 185, 129, 0.15); color: #059669; border: 1px solid rgba(16, 185, 129, 0.3); }
    .as-warn { background: rgba(245, 158, 11, 0.15); color: #D97706; border: 1px solid rgba(245, 158, 11, 0.3); }
    .as-risk { background: rgba(239, 68, 68, 0.15); color: #DC2626; border: 1px solid rgba(239, 68, 68, 0.3); }
    .as-list { margin: 6px 0 0; padding-left: 18px; }
    .as-mini-btn {
      border: 1px solid rgba(0,0,0,0.15);
      background: #fff;
      color: #333;
      border-radius: 4px;
      padding: 6px 10px;
      cursor: pointer;
      font-size: 11px;
      font-family: 'JetBrains Mono', monospace;
      font-weight: 600;
      transition: all 0.2s;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .as-mini-btn:hover { background: #f0f0f0; color: #000; border-color: rgba(0,0,0,0.3); }
    .as-pending-item { border-top: 1px solid #eaeaea; padding-top: 12px; margin-top: 12px; }
    .as-actions { display: flex; gap: 8px; margin-top: 8px; }
    .as-event-item { border-top: 1px solid #eaeaea; padding-top: 8px; margin-top: 8px; font-size: 13px; color: #333;}
    .as-event-meta { color: #666; font-size: 10px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
    .as-toast {
      position: fixed; right: 20px; top: 20px; z-index: ${config.zIndex};
      background: #fff; color: #111; border-radius: 6px; padding: 10px 14px;
      font: 500 12px/1.3 'Geist', system-ui, -apple-system, sans-serif;
      box-shadow: 0 10px 30px rgba(0,0,0,.15); border: 1px solid #ddd;
      opacity: 0; transform: translateY(-4px); transition: .2s ease;
      pointer-events: none;
    }
    .as-toast.show { opacity: 1; transform: translateY(0); }
    .as-timeline { display: flex; overflow-x: auto; gap: 12px; padding: 12px 0 4px; scrollbar-width: thin; }
    .as-timeline-node { flex: 0 0 auto; width: 150px; border: 1px solid #ddd; border-radius: 6px; padding: 8px; background: #fff; position: relative; display: flex; flex-direction: column; gap: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.02); }
    .as-timeline-node strong { font-size: 11px; display: block; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; color: #111; }
    .as-node-ts { font-size: 9px; color: #666; font-family: 'JetBrains Mono', monospace; }
    .as-node-desc { font-size: 10px; color: #444; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .as-node-btn { margin-top: auto; font-size: 10px; padding: 4px; text-align: center; }
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
        <div style="font-size:12px;color:#666;margin-top:6px;">No action proposed yet.</div>
      </div>
      <div class="as-card" id="as-current-assessment">
        <strong>Current Assessment</strong>
        <div style="font-size:12px;color:#666;margin-top:6px;">No live assessment yet.</div>
      </div>
      <div class="as-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>Pending Human Gates</strong>
          <button class="as-mini-btn" id="as-refresh-pending">Refresh</button>
        </div>
        <div id="as-pending-list" style="font-size:12px;color:#666;margin-top:6px;">No pending actions.</div>
      </div>
      </div>
      <div class="as-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>Live Agent Activity</strong>
          <button class="as-mini-btn" id="as-refresh-events">Refresh</button>
        </div>
        <div id="as-events-list" style="font-size:12px;color:#666;margin-top:6px;max-height:150px;overflow-y:auto;">No activity yet.</div>
      </div>
      <div class="as-card" style="grid-column: 1 / -1;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>Action Timeline & Rollback</strong>
          <button class="as-mini-btn" id="as-refresh-timeline">Refresh</button>
        </div>
        <div id="as-timeline" class="as-timeline">
           <div style="font-size:12px;color:#666;margin-top:6px;">No actions logged.</div>
        </div>
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
    loadTimeline();
    if (!eventsTimer) {
      eventsTimer = setInterval(() => {
        loadEvents();
        loadTimeline();
      }, config.eventsPollMs);
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
            <div style="color:#8F8F8F;">${item.reason}</div>
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
            <div style="margin-top:6px;font-size:12px;color:#8F8F8F;">
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

        const driftEvt = [...events].reverse().find(evt => evt.event_type === "intent.drift" || evt.event_type === "action.checkpoint");
        if (driftEvt && driftEvt.data && driftEvt.data.drift_score !== undefined && assessment) {
          const dScore = driftEvt.data.drift_score;
          let dIndicator = dScore < 0.3 ? "⚠️ High Drift Blocked" : dScore < 0.5 ? "⚠️ Minor Drift" : "✅ Aligned";
          if (assessment.innerHTML.indexOf("Intent Drift:") === -1) {
            assessment.innerHTML += `<div style="margin-top:4px;border-top:1px solid #333;padding-top:4px;"><strong>Intent Drift:</strong> ${dScore.toFixed(2)} (${dIndicator})</div>`;
          }
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

  async function loadTimeline() {
    const list = panel.querySelector("#as-timeline");
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/v1/sessions/${config.sessionId}/timeline`);
      if (!response.ok) return;
      const items = await response.json();
      if (!items.length) {
        list.innerHTML = `<div style="font-size:12px;color:#8F8F8F;margin-top:6px;">No actions logged.</div>`;
        return;
      }
      list.innerHTML = items.map((item) => {
        const ts = new Date(item.timestamp * 1000).toLocaleTimeString();
        const driftColor = item.drift_score < 0.3 ? "color:#EF4444;" : item.drift_score < 0.5 ? "color:#F59E0B;" : "color:#10B981;";
        return `
          <div class="as-timeline-node">
            <div class="as-node-ts">${ts}</div>
            <strong>${item.action_type}</strong>
            <div class="as-node-desc" title="${item.description}">${item.description}</div>
            <div style="font-size:9px; ${driftColor} font-family:monospace; margin-top:2px;">Drift: ${item.drift_score.toFixed(2)}</div>
            <button class="as-mini-btn as-node-btn" data-rollback-id="${item.id}">Rollback Here</button>
          </div>
        `;
      }).join("");
    } catch (err) { }
  }

  async function rollbackTo(checkpointId) {
    if (!confirm("Are you sure you want to rollback to this checkpoint? Subsequent actions will be reverted.")) return;
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/v1/sessions/${config.sessionId}/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checkpoint_id: checkpointId })
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      showToast("Rollback successful!");
      loadTimeline();
      loadEvents();
    } catch (err) {
      showToast(`Rollback failed: ${err.message}`);
    }
  }

  launcher.addEventListener("click", openPanel);
  panel.querySelector(".as-close").addEventListener("click", closePanel);
  panel.querySelector("#as-refresh-pending").addEventListener("click", loadPendingGates);
  panel.querySelector("#as-refresh-events").addEventListener("click", loadEvents);
  panel.querySelector("#as-refresh-timeline").addEventListener("click", loadTimeline);
  panel.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const gateId = target.getAttribute("data-gate-id");
    const decision = target.getAttribute("data-decision");
    if (gateId && decision) {
      decideGate(gateId, decision);
    }
    const rollbackId = target.getAttribute("data-rollback-id");
    if (rollbackId) {
      rollbackTo(rollbackId);
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
