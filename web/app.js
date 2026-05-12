const views = {
  input: document.querySelector("#inputView"),
  analyzing: document.querySelector("#analyzingView"),
  proposal: document.querySelector("#proposalView"),
  executing: document.querySelector("#executingView"),
  success: document.querySelector("#successView"),
  error: document.querySelector("#errorView"),
};

const goal = document.querySelector("#goal");
const origin = document.querySelector("#origin");
const city = document.querySelector("#city");
const planBtn = document.querySelector("#planBtn");
const confirmBtn = document.querySelector("#confirmBtn");
const editBtn = document.querySelector("#editBtn");
const backBtn = document.querySelector("#backBtn");
const newPlanBtn = document.querySelector("#newPlanBtn");
const themeBtn = document.querySelector("#themeBtn");

const analyzingArc = document.querySelector("#analyzingArc");
const analyzingPercent = document.querySelector("#analyzingPercent");
const analyzingSteps = document.querySelector("#analyzingSteps");
const executingArc = document.querySelector("#executingArc");
const executingPercent = document.querySelector("#executingPercent");
const executingSteps = document.querySelector("#executingSteps");

const planTitle = document.querySelector("#planTitle");
const planSummary = document.querySelector("#planSummary");
const partySize = document.querySelector("#partySize");
const transportMode = document.querySelector("#transportMode");
const actionCount = document.querySelector("#actionCount");
const finishTime = document.querySelector("#finishTime");
const timeline = document.querySelector("#timeline");
const participantChips = document.querySelector("#participantChips");
const routeChips = document.querySelector("#routeChips");
const actionChips = document.querySelector("#actionChips");
const riskSection = document.querySelector("#riskSection");
const riskChips = document.querySelector("#riskChips");
const successMessage = document.querySelector("#successMessage");
const receiptStatus = document.querySelector("#receiptStatus");
const receiptItems = document.querySelector("#receiptItems");
const errorMessage = document.querySelector("#errorMessage");

const analyzingCopy = [
  "提取时间与参与者画像",
  "解析距离偏好与交通方式",
  "匹配附近活动与餐饮资源",
  "生成可执行活动方案",
];

let currentPlan = null;
let lastExecution = null;

initTheme();
renderStepList(analyzingSteps, analyzingCopy, 0);
renderStepList(executingSteps, [], 0);

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    goal.value = button.dataset.example;
    goal.focus();
  });
});

themeBtn.addEventListener("click", () => {
  document.body.classList.toggle("dark");
  localStorage.setItem("nearnow-theme", document.body.classList.contains("dark") ? "dark" : "light");
});

planBtn.addEventListener("click", async () => {
  if (!goal.value.trim()) return;
  currentPlan = null;
  lastExecution = null;
  showView("analyzing");
  animateProgress({
    arc: analyzingArc,
    label: analyzingPercent,
    container: analyzingSteps,
    steps: analyzingCopy,
    duration: 900,
  });

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
    await delay(950);
    if (!payload.success) {
      renderError(payload.error.message);
      return;
    }
    currentPlan = payload.data;
    renderPlan(currentPlan);
    showView("proposal");
  } catch (error) {
    renderError(error.message);
  }
});

confirmBtn.addEventListener("click", async () => {
  if (!currentPlan) return;
  const copy = currentPlan.pending_actions.map((action) => actionLabel(action.type, action.target));
  showView("executing");
  renderStepList(executingSteps, copy, 0);
  animateProgress({
    arc: executingArc,
    label: executingPercent,
    container: executingSteps,
    steps: copy,
    duration: 1000,
  });

  try {
    const response = await fetch("/api/agent/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_id: currentPlan.plan_id,
        confirmed_action_ids: currentPlan.pending_actions.map((action) => action.action_id),
      }),
    });
    const payload = await response.json();
    await delay(1050);
    if (!payload.success) {
      renderError(payload.error.message);
      return;
    }
    lastExecution = payload.data;
    renderSuccess(lastExecution);
    showView("success");
  } catch (error) {
    renderError(error.message);
  }
});

editBtn.addEventListener("click", () => showView("input"));
backBtn.addEventListener("click", () => showView("input"));
newPlanBtn.addEventListener("click", () => {
  currentPlan = null;
  lastExecution = null;
  goal.focus();
  showView("input");
});

function showView(name) {
  Object.entries(views).forEach(([key, view]) => {
    view.hidden = key !== name;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderPlan(plan) {
  const selectedRoute = plan.route_options.find((route) => route.selected) || plan.route_options[0];
  const lastSchedule = plan.schedule[plan.schedule.length - 1];

  planTitle.textContent = plan.title;
  planSummary.textContent = plan.summary;
  partySize.textContent = inferPartySize(plan);
  transportMode.textContent = selectedRoute ? modeLabel(selectedRoute.mode) : "-";
  actionCount.textContent = plan.pending_actions.length;
  finishTime.textContent = lastSchedule ? lastSchedule.end_time : "-";

  timeline.innerHTML = plan.schedule.map(renderScheduleItem).join("");
  participantChips.innerHTML = renderChips(plan.participant_summary);
  routeChips.innerHTML = plan.route_options.map(renderRouteItem).join("");
  actionChips.innerHTML = renderChips(plan.pending_actions.map((action) => `${actionTypeLabel(action.type)} · ${action.target}`));

  riskSection.hidden = !plan.risk_notes.length;
  riskChips.innerHTML = renderChips(plan.risk_notes);
}

function renderSuccess(result) {
  successMessage.textContent = result.final_message;
  receiptStatus.textContent = result.execution_status === "completed" ? "执行成功" : "部分完成";
  receiptItems.innerHTML = result.results
    .map((item) => {
      const no = item.confirmation_no || item.message_id || item.booking_id || "已记录";
      return `
        <article class="receipt-item">
          <div>
            <span>${escapeHtml(actionTypeLabel(item.type))}</span>
            <strong>${escapeHtml(item.status)}</strong>
          </div>
          <code>${escapeHtml(no)}</code>
        </article>
      `;
    })
    .join("");
}

function renderError(message) {
  errorMessage.textContent = message;
  showView("error");
}

function renderScheduleItem(item, index) {
  const badge = item.type === "travel" ? modeLabel(item.transport_mode) : item.typeLabel || typeLabel(item.type);
  return `
    <article class="timeline-item">
      <div class="timeline-dot"><span>${index + 1}</span></div>
      <div class="timeline-card">
        <div class="timeline-card-head">
          <span>${escapeHtml(item.start_time)} - ${escapeHtml(item.end_time)}</span>
          <em>${escapeHtml(badge)}</em>
        </div>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.location)}</p>
        <div class="reason">${escapeHtml(item.reason)}</div>
      </div>
    </article>
  `;
}

function renderRouteItem(route) {
  return `
    <article class="route-item ${route.selected ? "selected" : ""}">
      <div>
        <strong>${escapeHtml(modeLabel(route.mode))}</strong>
        <span>${route.duration_minutes} 分钟 · ${route.distance_km} km</span>
      </div>
      <em>${route.selected ? "已选" : `${route.estimated_cost} 元`}</em>
    </article>
  `;
}

function renderChips(values) {
  return values.map((value) => `<span class="chip">${escapeHtml(value)}</span>`).join("");
}

function renderStepList(container, steps, progress) {
  container.innerHTML = steps
    .map((step, index) => {
      const threshold = ((index + 1) / steps.length) * 100;
      const done = progress >= threshold;
      const active = progress > (index / steps.length) * 100 && progress < threshold;
      return `
        <div class="process-step ${done ? "done" : ""} ${active ? "active" : ""}">
          <span></span>
          <p>${escapeHtml(step)}</p>
        </div>
      `;
    })
    .join("");
}

function animateProgress({ arc, label, container, steps, duration }) {
  const circumference = 326.7;
  arc.style.strokeDasharray = circumference;
  arc.style.strokeDashoffset = circumference;
  let progress = 0;
  renderStepList(container, steps, 0);
  label.textContent = "0%";

  const timer = setInterval(() => {
    progress = Math.min(100, progress + 25);
    arc.style.strokeDashoffset = circumference - (progress / 100) * circumference;
    label.textContent = `${progress}%`;
    renderStepList(container, steps, progress);
    if (progress >= 100) clearInterval(timer);
  }, duration / 4);
}

function initTheme() {
  const saved = localStorage.getItem("nearnow-theme");
  const hour = new Date().getHours();
  if (saved === "dark" || (!saved && (hour < 6 || hour >= 18))) {
    document.body.classList.add("dark");
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  }[mode] || mode || "-";
}

function typeLabel(type) {
  return {
    travel: "出行",
    activity: "活动",
    restaurant: "餐厅",
  }[type] || type;
}

function actionTypeLabel(type) {
  return {
    book_activity: "预约活动",
    reserve_restaurant: "预订餐厅",
    send_notification: "发送计划",
  }[type] || type;
}

function actionLabel(type, target) {
  return `${actionTypeLabel(type)}：${target}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
