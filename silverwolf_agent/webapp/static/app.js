const state = {
  lastId: 0,
  eventSource: null,
  pendingReplies: 0,
};

const els = {
  list: document.querySelector("#message-list"),
  empty: document.querySelector("#empty-state"),
  template: document.querySelector("#message-template"),
  form: document.querySelector("#chat-form"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  typing: document.querySelector("#typing-state"),
  statusDot: document.querySelector("#status-dot"),
  statusText: document.querySelector("#status-text"),
  model: document.querySelector("#model-name"),
  plannerMode: document.querySelector("#planner-mode"),
  time: document.querySelector("#server-time"),
  timezone: document.querySelector("#timezone"),
  agentAge: document.querySelector("#agent-age"),
  agentBirthday: document.querySelector("#agent-birthday"),
  followUpState: document.querySelector("#follow-up-state"),
  planCount: document.querySelector("#plan-count"),
  planList: document.querySelector("#plan-list"),
  refreshPlans: document.querySelector("#refresh-plans"),
  tick: document.querySelector("#tick-button"),
  lastEventTime: document.querySelector("#last-event-time"),
  systemLog: document.querySelector("#system-log"),
  timeInputs: {
    morning: document.querySelector("#time-morning"),
    noon: document.querySelector("#time-noon"),
    evening: document.querySelector("#time-evening"),
  },
};

function logLine(message) {
  const line = document.createElement("p");
  const now = new Date().toLocaleTimeString("zh-CN", {
    hour12: false,
  });
  line.textContent = `[${now}] ${message}`;
  els.systemLog.appendChild(line);
  els.systemLog.scrollTop = els.systemLog.scrollHeight;
}

function formatTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    hour12: false,
  });
}

function roleLabel(event) {
  if (event.role === "user") return "STAR";
  if (event.role === "system") return "SYSTEM";
  return event.source === "proactive"
    ? "SILVER WOLF // PROACTIVE"
    : "SILVER WOLF";
}

function renderMessage(event) {
  if (!event || !event.event_id) return;
  if (document.querySelector(`[data-event-id="${event.event_id}"]`)) {
    return;
  }

  els.empty?.remove();

  const node = els.template.content.firstElementChild.cloneNode(true);
  node.dataset.eventId = String(event.event_id);
  node.classList.add(event.role || "assistant");

  if (event.source === "proactive") {
    node.classList.add("proactive");
  }

  node.querySelector(".message-role").textContent = roleLabel(event);
  node.querySelector("time").textContent = formatTime(event.timestamp);
  node.querySelector("time").dateTime = event.timestamp || "";
  node.querySelector(".message-body").textContent = event.content || "";

  const tags = node.querySelector(".message-tags");
  const tagValues = [];

  if (event.source === "proactive") {
    tagValues.push("PROACTIVE");
  }
  if (event.category && event.category !== "conversation") {
    tagValues.push(String(event.category).toUpperCase());
  }
  if (Number.isFinite(event.weight)) {
    tagValues.push(`W:${event.weight}`);
  }

  const templateGroup = event.metadata?.template_group;
  const templateId = event.metadata?.template_id;
  if (templateGroup) {
    tagValues.push(String(templateGroup).toUpperCase());
  }
  if (templateId) {
    tagValues.push(String(templateId).toUpperCase());
  }

  for (const value of tagValues) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = value;
    tags.appendChild(tag);
  }

  els.list.appendChild(node);
  els.list.scrollTop = els.list.scrollHeight;
  state.lastId = Math.max(state.lastId, Number(event.event_id));
  els.lastEventTime.textContent = formatDateTime(event.timestamp);

  if (
    event.role === "system" ||
    (
      event.role === "assistant" &&
      event.source !== "proactive"
    )
  ) {
    state.pendingReplies = Math.max(0, state.pendingReplies - 1);
    updateTyping();
  }
}

function updateTyping() {
  const visible = state.pendingReplies > 0;
  els.typing.classList.toggle("visible", visible);
  els.send.disabled = visible;
}

async function loadHistory() {
  const response = await fetch("/api/messages");
  if (!response.ok) throw new Error("history request failed");
  const data = await response.json();

  for (const event of data.messages || []) {
    renderMessage(event);
  }
  state.lastId = Math.max(state.lastId, Number(data.last_id || 0));
}

function connectEvents() {
  if (state.eventSource) {
    state.eventSource.close();
  }

  const source = new EventSource(`/api/events?after=${state.lastId}`);
  state.eventSource = source;

  source.addEventListener("open", () => {
    logLine("SSE channel connected");
  });

  source.addEventListener("message", (raw) => {
    try {
      const event = JSON.parse(raw.data);
      renderMessage(event);
    } catch (error) {
      logLine(`invalid event: ${error.message}`);
    }
  });

  source.addEventListener("error", () => {
    logLine("SSE channel reconnecting");
  });
}

async function sendMessage(text) {
  state.pendingReplies += 1;
  updateTyping();

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message: text }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    state.pendingReplies = Math.max(0, state.pendingReplies - 1);
    updateTyping();
    throw new Error(data.error || "message rejected");
  }
}

function autoResize() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(150, els.input.scrollHeight)}px`;
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.input.value.trim();
  if (!text) return;

  els.input.value = "";
  autoResize();

  try {
    await sendMessage(text);
  } catch (error) {
    logLine(`send failed: ${error.message}`);
  } finally {
    els.input.focus();
  }
});

els.input.addEventListener("input", autoResize);
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.form.requestSubmit();
  }
});

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("status request failed");
    const data = await response.json();

    const online = Boolean(data.runtime_running);
    els.statusDot.classList.toggle("online", online);
    els.statusText.textContent = online ? "LINK ONLINE" : "LINK DEGRADED";
    els.model.textContent = data.offline
      ? `${data.model} / OFFLINE`
      : data.model;
    els.plannerMode.textContent = data.planner_llm_available
      ? "MODEL + RULE"
      : "RULE FALLBACK";
    els.time.textContent = formatTime(data.now);
    els.timezone.textContent = data.timezone;
    els.agentAge.textContent = `${data.agent_age ?? "--"} Y`;
    els.agentBirthday.textContent = data.agent_birthday ?? "--";
    els.followUpState.textContent = data.pending_follow_up
      ? "WAITING"
      : "IDLE";
    els.planCount.textContent = String(data.plan_count ?? 0);

    if (data.last_scheduler_error) {
      logLine(`scheduler: ${data.last_scheduler_error}`);
    }
  } catch (error) {
    els.statusDot.classList.remove("online");
    els.statusText.textContent = "DISCONNECTED";
  }
}

async function refreshPlans() {
  try {
    const response = await fetch("/api/plans", {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("plans request failed");
    const data = await response.json();
    const plans = (data.plans || []).filter(
      (plan) => plan.status === "pending",
    );

    els.planList.replaceChildren();

    if (!plans.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "暂无待执行计划。";
      els.planList.appendChild(empty);
      return;
    }

    for (const plan of plans) {
      const item = document.createElement("article");
      item.className = "plan-item";

      const title = document.createElement("h3");
      title.textContent = plan.title || "未命名计划";

      const meta = document.createElement("p");
      meta.textContent =
        `${formatDateTime(plan.due_at)} · W:${plan.importance}`;

      const cancel = document.createElement("button");
      cancel.className = "ghost-button";
      cancel.type = "button";
      cancel.textContent = "CANCEL";
      cancel.addEventListener("click", async () => {
        await fetch(`/api/plans/${encodeURIComponent(plan.plan_id)}`, {
          method: "DELETE",
        });
        await refreshPlans();
        await refreshStatus();
      });

      item.append(title, meta, cancel);
      els.planList.appendChild(item);
    }
  } catch (error) {
    logLine(`plans failed: ${error.message}`);
  }
}

async function loadTimeSettings() {
  try {
    const response = await fetch("/api/time-settings", {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("time settings request failed");
    const data = await response.json();
    const slots = data.slots || {};

    for (const [name, input] of Object.entries(els.timeInputs)) {
      if (input && slots[name]?.time) {
        input.value = slots[name].time;
      }
    }
  } catch (error) {
    logLine(`time settings failed: ${error.message}`);
  }
}

for (const [slot, input] of Object.entries(els.timeInputs)) {
  input.addEventListener("change", async () => {
    try {
      const response = await fetch(`/api/time-settings/${slot}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          time: input.value,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "update failed");
      }
      logLine(`${slot} updated to ${input.value}`);
    } catch (error) {
      logLine(`time update failed: ${error.message}`);
    }
  });
}

els.tick.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/proactive/tick", {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "tick failed");
    logLine("proactive check submitted");
  } catch (error) {
    logLine(`tick failed: ${error.message}`);
  }
});

els.refreshPlans.addEventListener("click", refreshPlans);

async function boot() {
  try {
    await loadHistory();
  } catch (error) {
    logLine(`history failed: ${error.message}`);
  }

  connectEvents();
  await Promise.all([
    refreshStatus(),
    refreshPlans(),
    loadTimeSettings(),
  ]);

  window.setInterval(refreshStatus, 5000);
  window.setInterval(refreshPlans, 15000);
  els.input.focus();
}

boot();
