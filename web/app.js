const goal = document.querySelector("#goal");
const origin = document.querySelector("#origin");
const city = document.querySelector("#city");
const planBtn = document.querySelector("#planBtn");
const confirmBtn = document.querySelector("#confirmBtn");
const output = document.querySelector("#output");
const partySize = document.querySelector("#partySize");
const transportMode = document.querySelector("#transportMode");
const actionCount = document.querySelector("#actionCount");

let currentPlan = null;

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    goal.value = button.dataset.example;
    goal.focus();
  });
});

planBtn.addEventListener("click", async () => {
  setLoading(true);
  currentPlan = null;
  confirmBtn.disabled = true;
  try {
    const response = await fetch("/api/agent/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: goal.value,
        mode: "mock",
        user_context: {
          home_location: origin.value,
          city: city.value,
          coordinates: { lat: 39.9957, lng: 116.4813 },
          location_permission_granted: false,
        },
      }),
    });
    const payload = await response.json();
    if (!payload.success) {
      renderError(payload.error.message);
      return;
    }
    currentPlan = payload.data;
    renderPlan(currentPlan);
    confirmBtn.disabled = !currentPlan.requires_confirmation || currentPlan.pending_actions.length === 0;
  } catch (error) {
    renderError(error.message);
  } finally {
    setLoading(false);
  }
});

confirmBtn.addEventListener("click", async () => {
  if (!currentPlan) return;
  confirmBtn.disabled = true;
  const response = await fetch("/api/agent/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_id: currentPlan.plan_id,
      confirmed_action_ids: currentPlan.pending_actions.map((action) => action.action_id),
    }),
  });
  const payload = await response.json();
  if (!payload.success) {
    renderError(payload.error.message);
    return;
  }
  renderExecution(payload.data);
});

function setLoading(isLoading) {
  planBtn.disabled = isLoading;
  planBtn.textContent = isLoading ? "生成中..." : "生成方案";
}

function renderPlan(plan) {
  output.classList.remove("empty");
  const selectedRoute = plan.route_options.find((route) => route.selected) || plan.route_options[0];
  partySize.textContent = inferPartySize(plan);
  transportMode.textContent = selectedRoute ? modeLabel(selectedRoute.mode) : "-";
  actionCount.textContent = plan.pending_actions.length;

  output.innerHTML = `
    <h2>${escapeHtml(plan.title)}</h2>
    <p>${escapeHtml(plan.summary)}</p>
    <h3 class="section-title">时间轴</h3>
    <div class="timeline">
      ${plan.schedule.map(renderScheduleItem).join("")}
    </div>
    <h3 class="section-title">参与者约束</h3>
    <div class="chips">
      ${plan.participant_summary.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("")}
    </div>
    <h3 class="section-title">交通方式比较</h3>
    <div class="chips">
      ${plan.route_options.map(renderRouteChip).join("")}
    </div>
    <h3 class="section-title">确认后执行</h3>
    <div class="chips">
      ${plan.pending_actions.map((action) => `<span class="chip">${escapeHtml(action.type)}：${escapeHtml(action.target)}</span>`).join("")}
    </div>
    ${plan.risk_notes.length ? `<h3 class="section-title">风险提示</h3><div class="chips">${plan.risk_notes.map((note) => `<span class="chip">${escapeHtml(note)}</span>`).join("")}</div>` : ""}
  `;
}

function renderExecution(result) {
  const block = document.createElement("div");
  block.innerHTML = `
    <h3 class="section-title">执行结果</h3>
    <div class="chips">
      ${result.results.map((item) => `<span class="chip">${escapeHtml(item.type)}：${escapeHtml(item.status)}</span>`).join("")}
    </div>
    <p>${escapeHtml(result.final_message)}</p>
  `;
  output.appendChild(block);
}

function renderScheduleItem(item) {
  return `
    <div class="item">
      <div class="time">${escapeHtml(item.start_time)}-${escapeHtml(item.end_time)}</div>
      <div>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.location)} · ${escapeHtml(item.reason)}</p>
      </div>
    </div>
  `;
}

function renderRouteChip(route) {
  const selected = route.selected ? "已选 " : "";
  return `<span class="chip">${selected}${modeLabel(route.mode)} · ${route.duration_minutes} 分钟 · ${route.distance_km} km</span>`;
}

function renderError(message) {
  output.classList.remove("empty");
  output.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  partySize.textContent = "-";
  transportMode.textContent = "-";
  actionCount.textContent = "-";
}

function inferPartySize(plan) {
  const action = plan.pending_actions.find((item) => item.payload && item.payload.party_size);
  return action ? action.payload.party_size : "-";
}

function modeLabel(mode) {
  return {
    walking: "步行",
    driving: "驾车",
    public_transit: "公交/地铁",
    ride_hailing: "网约车",
    cycling: "骑行",
  }[mode] || mode;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

