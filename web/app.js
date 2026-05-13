const views = {
  login: document.querySelector("#loginView"),
  input: document.querySelector("#inputView"),
  analyzing: document.querySelector("#analyzingView"),
  proposal: document.querySelector("#proposalView"),
  executing: document.querySelector("#executingView"),
  success: document.querySelector("#successView"),
  error: document.querySelector("#errorView"),
};

const loginForm = document.querySelector("#loginForm");
const loginUsername = document.querySelector("#loginUsername");
const loginPassword = document.querySelector("#loginPassword");
const loginDisplayName = document.querySelector("#loginDisplayName");
const loginError = document.querySelector("#loginError");
const sessionPill = document.querySelector("#sessionPill");
const sessionName = document.querySelector("#sessionName");
const logoutBtn = document.querySelector("#logoutBtn");

const goal = document.querySelector("#goal");
const origin = document.querySelector("#origin");
const companions = document.querySelector("#companions");
const planBtn = document.querySelector("#planBtn");
const locateBtn = document.querySelector("#locateBtn");
const confirmBtn = document.querySelector("#confirmBtn");
const editBtn = document.querySelector("#editBtn");
const backBtn = document.querySelector("#backBtn");
const newPlanBtn = document.querySelector("#newPlanBtn");
const themeBtn = document.querySelector("#themeBtn");
const locationStatus = document.querySelector("#locationStatus");

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
const manualLocationHelp = "出发位置格式：城市 + 区/县 + 商圈/地标，例如 北京 朝阳区 望京 SOHO。可手动输入，也可定位后修改。";
const defaultCity = "北京";
const knownCities = [
  "北京",
  "上海",
  "广州",
  "深圳",
  "杭州",
  "成都",
  "重庆",
  "天津",
  "南京",
  "苏州",
  "武汉",
  "西安",
  "厦门",
  "长沙",
  "郑州",
  "青岛",
  "纽约",
  "旧金山",
];

let currentPlan = null;
let lastExecution = null;
let currentLocation = null;
let currentCity = inferCityFromLocation(origin.value) || defaultCity;
let currentUser = null;

initTheme();
renderStepList(analyzingSteps, analyzingCopy, 0);
renderStepList(executingSteps, [], 0);
updateManualLocationStatus();
initSession();

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: loginUsername.value,
        password: loginPassword.value,
        display_name: loginDisplayName.value,
      }),
    });
    const payload = await response.json();
    if (!payload.success) {
      loginError.textContent = payload.error?.message || "登录失败";
      return;
    }
    applyUser(payload.data.user);
    await loadCompanions();
    showView("input");
  } catch (error) {
    loginError.textContent = error.message;
  }
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  currentUser = null;
  currentPlan = null;
  lastExecution = null;
  companions.value = "";
  updateSessionHeader();
  showView("login");
});

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

origin.addEventListener("input", () => {
  if (currentLocation) {
    syncLocatedAddressEdit();
    return;
  }
  currentCity = inferCityFromLocation(origin.value) || currentCity || defaultCity;
  updateManualLocationStatus();
});

locateBtn.addEventListener("click", () => {
  if (!("geolocation" in navigator)) {
    setLocationStatus("当前浏览器不支持定位，请手动输入出发地。", "error");
    return;
  }

  locateBtn.disabled = true;
  locateBtn.textContent = "定位中...";
  setLocationStatus("正在请求浏览器定位授权...", "pending");

  navigator.geolocation.getCurrentPosition(
    (position) => {
      resolveBrowserLocation(position);
    },
    (error) => {
      currentLocation = null;
      setLocationStatus(locationErrorMessage(error), "error");
      locateBtn.disabled = false;
      locateBtn.textContent = "定位";
    },
    {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 60000,
    },
  );
});

planBtn.addEventListener("click", async () => {
  if (!currentUser) {
    showView("login");
    loginUsername.focus();
    return;
  }
  if (!goal.value.trim()) return;
  const userContext = buildUserContext();
  if (userContext.error) {
    setLocationStatus(userContext.error, "error");
    origin.focus();
    return;
  }

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
        mode: "real",
        user_context: userContext,
        companions: parseCompanions(companions.value),
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
        selected_route_mode: selectedRouteMode(currentPlan),
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

routeChips.addEventListener("click", (event) => {
  const routeButton = event.target.closest("[data-route-mode]");
  if (!routeButton || !currentPlan) return;
  selectRoute(routeButton.dataset.routeMode);
  renderPlan(currentPlan);
});

function showView(name) {
  Object.entries(views).forEach(([key, view]) => {
    view.hidden = key !== name;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function initSession() {
  try {
    const response = await fetch("/api/auth/me");
    const payload = await response.json();
    if (payload.success && payload.data.authenticated) {
      applyUser(payload.data.user);
      await loadCompanions();
      showView("input");
      return;
    }
  } catch (error) {
    loginError.textContent = error.message;
  }
  updateSessionHeader();
  showView("login");
}

function applyUser(user) {
  currentUser = user;
  updateSessionHeader();
}

function updateSessionHeader() {
  sessionPill.hidden = !currentUser;
  sessionName.textContent = currentUser ? currentUser.display_name || currentUser.username : "未登录";
}

async function loadCompanions() {
  try {
    const response = await fetch("/api/companions");
    const payload = await response.json();
    if (!payload.success || !Array.isArray(payload.data) || payload.data.length === 0) return;
    companions.value = payload.data.map(formatCompanionLine).join("\n");
  } catch (error) {
    return;
  }
}

function renderPlan(plan) {
  preparePlanForRouteEditing(plan);
  const selectedRoute = plan.route_options.find((route) => route.selected) || plan.route_options[0];
  const lastSchedule = plan.schedule[plan.schedule.length - 1];

  planTitle.textContent = plan.title;
  planSummary.textContent = plan.summary;
  partySize.textContent = inferPartySize(plan);
  transportMode.textContent = selectedRoute ? modeLabel(selectedRoute.mode) : "-";
  actionCount.textContent = plan.pending_actions.length;
  finishTime.textContent = lastSchedule ? lastSchedule.end_time : "-";

  timeline.innerHTML = renderTimeline(plan);
  participantChips.innerHTML = renderChips(plan.participant_summary);
  routeChips.innerHTML = plan.route_options.map(renderRouteItem).join("");
  actionChips.innerHTML = renderChips(plan.pending_actions.map((action) => `${actionTypeLabel(action.type)} · ${action.target}`));

  riskSection.hidden = !plan.risk_notes.length;
  riskChips.innerHTML = renderChips(plan.risk_notes);
}

function preparePlanForRouteEditing(plan) {
  if (plan.route_edit_ready) return;
  plan.route_edit_ready = true;
  plan.base_summary = plan.summary;
  plan.static_risk_notes = plan.risk_notes.filter((note) => !isRouteRiskNote(note));
  if (plan.route_options.length && !plan.route_options.some((route) => route.selected)) {
    plan.route_options[0].selected = true;
  }
}

function selectRoute(mode) {
  const route = currentPlan.route_options.find((item) => item.mode === mode);
  if (!route) return;

  const travelIndex = currentPlan.schedule.findIndex((item) => item.type === "travel");
  const travelItem = currentPlan.schedule[travelIndex];
  const previousDuration = travelItem?.travel_minutes || selectedRoute(currentPlan)?.duration_minutes || route.duration_minutes;
  const deltaMinutes = route.duration_minutes - previousDuration;

  currentPlan.route_options.forEach((item) => {
    item.selected = item.mode === route.mode;
  });

  if (travelItem) {
    travelItem.end_time = addMinutes(travelItem.start_time, route.duration_minutes);
    travelItem.travel_minutes = route.duration_minutes;
    travelItem.transport_mode = route.mode;
    travelItem.reason = routeReason(route.mode);
    if (deltaMinutes) {
      currentPlan.schedule.slice(travelIndex + 1).forEach((item) => shiftScheduleItem(item, deltaMinutes));
      syncPendingActionTimes(currentPlan);
    }
  }

  updateRouteRiskNotes(currentPlan, route);
  updateRouteSummary(currentPlan, route);
}

function selectedRoute(plan) {
  return plan.route_options.find((route) => route.selected) || plan.route_options[0];
}

function selectedRouteMode(plan) {
  return selectedRoute(plan)?.mode || "";
}

function shiftScheduleItem(item, minutes) {
  item.start_time = addMinutes(item.start_time, minutes);
  item.end_time = addMinutes(item.end_time, minutes);
}

function syncPendingActionTimes(plan) {
  const activity = plan.schedule.find((item) => item.type === "activity");
  const restaurant = plan.schedule.find((item) => item.type === "restaurant");
  plan.pending_actions.forEach((action) => {
    if (action.type === "book_activity" && activity) {
      action.payload.start_time = activity.start_time;
    }
    if (action.type === "reserve_restaurant" && restaurant) {
      action.payload.arrival_time = restaurant.start_time;
    }
  });
}

function updateRouteSummary(plan, route) {
  const lastSchedule = plan.schedule[plan.schedule.length - 1];
  const baseSummary = plan.base_summary || plan.summary;
  const withFinishTime = lastSchedule
    ? baseSummary.replace(/\d{2}:\d{2}\s*前结束/, `${lastSchedule.end_time} 前结束`)
    : baseSummary;
  plan.summary = `${withFinishTime} 当前交通已选择${modeLabel(route.mode)}。`;
}

function updateRouteRiskNotes(plan, route) {
  const notes = [...(plan.static_risk_notes || plan.risk_notes.filter((note) => !isRouteRiskNote(note)))];
  notes.push(routeRiskNote(route));
  plan.risk_notes = notes.filter(Boolean);
}

function isRouteRiskNote(note) {
  return /路况|步行距离|已选择|骑行|公交\/地铁|交通/.test(String(note));
}

function routeRiskNote(route) {
  const prefix = `已选择${modeLabel(route.mode)}，预计 ${route.duration_minutes} 分钟、${route.distance_km} km。`;
  if (route.mode === "driving" || route.mode === "ride_hailing") {
    return `${prefix}出发前建议复查实时路况和上车/停车位置。`;
  }
  if (route.mode === "walking") {
    return `${prefix}${route.distance_km > 2 ? "距离偏长，儿童或老人同行时建议确认体力。" : "适合近距离慢节奏安排。"}`;
  }
  if (route.mode === "cycling") {
    return `${prefix}骑行前请确认同行者安全装备和道路条件。`;
  }
  if (route.mode === "public_transit") {
    return `${prefix}出发前建议复查实时班次和换乘距离。`;
  }
  return prefix;
}

function renderTimeline(plan) {
  if (plan.schedule.length) {
    return plan.schedule.map(renderScheduleItem).join("");
  }
  const reasons = plan.risk_notes.length
    ? plan.risk_notes
    : [plan.final_message || "当前条件下没有可执行时间轴。"];
  return `
    <article class="empty-timeline">
      <strong>暂未生成可执行时间轴</strong>
      <p>${escapeHtml(plan.final_message || plan.summary || "需要补充或放宽条件后继续规划。")}</p>
      <div class="chips">${renderChips(reasons)}</div>
    </article>
  `;
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
    <button class="route-item ${route.selected ? "selected" : ""}" type="button" data-route-mode="${escapeHtml(route.mode)}" aria-pressed="${route.selected ? "true" : "false"}">
      <div>
        <strong>${escapeHtml(modeLabel(route.mode))}</strong>
        <span>${route.duration_minutes} 分钟 · ${route.distance_km} km</span>
      </div>
      <em>${route.selected ? "已选" : `${route.estimated_cost} 元`}</em>
    </button>
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

function routeReason(mode) {
  return {
    walking: "已按你的选择改为步行，适合距离较近、节奏更松的安排。",
    driving: "已按你的选择改为驾车，适合多人同行和减少步行。",
    public_transit: "已按你的选择改为公交/地铁，成本更低，适合多人统一出行。",
    ride_hailing: "已按你的选择改为网约车，减少换乘和停车成本。",
    cycling: "已按你的选择改为骑行，适合轻量出行并控制成本。",
  }[mode] || "已按你的选择更新交通方式。";
}

function addMinutes(timeText, minutes) {
  const [hour, minute] = String(timeText || "00:00").split(":").map((value) => Number.parseInt(value, 10));
  const date = new Date(2000, 0, 1, Number.isFinite(hour) ? hour : 0, Number.isFinite(minute) ? minute : 0);
  date.setMinutes(date.getMinutes() + minutes);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
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

function parseCompanions(value) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/).filter(Boolean);
      const [name, relation, ...contactParts] = parts;
      const contactValue = contactParts.join(" ");
      return {
        name: name || "",
        relation: relation || "同行者",
        contact_method: inferContactMethod(contactValue),
        contact_value: contactValue,
      };
    })
    .filter((item) => item.name);
}

function formatCompanionLine(item) {
  return [item.name, item.relation, item.contact_value].filter(Boolean).join(" ");
}

function inferContactMethod(value) {
  if (!value) return "";
  if (value.includes("@")) return "email";
  if (/^[+\d][\d\s-]+$/.test(value)) return "phone";
  return "wechat";
}

function buildUserContext() {
  if (currentLocation) {
    return {
      home_location: currentLocation.home_location || origin.value || "我的大概位置",
      city: currentLocation.city || currentCity,
      coordinates: {
        lat: currentLocation.lat,
        lng: currentLocation.lng,
      },
      location_permission_granted: true,
      location_source: "browser",
      accuracy_m: currentLocation.accuracy_m,
      precision: currentLocation.precision,
      district: currentLocation.district,
      landmark: currentLocation.landmark,
      formatted_address: currentLocation.formatted_address,
      address_source: currentLocation.address_source,
      address_confidence: currentLocation.address_confidence,
    };
  }

  const manualLocation = parseManualLocation(origin.value, currentCity);
  if (!manualLocation.valid) {
    return { error: manualLocation.message };
  }

  currentCity = manualLocation.city;
  return {
    home_location: manualLocation.label,
    city: manualLocation.city,
    location_permission_granted: false,
    location_source: "manual",
    manual_location_format: manualLocation.format,
    precision: manualLocation.precision,
    district: manualLocation.district,
    landmark: manualLocation.landmark,
    formatted_address: manualLocation.label,
  };
}

async function resolveBrowserLocation(position) {
  const coarseLocation = coarseCoordinates(position.coords.latitude, position.coords.longitude);
  currentLocation = {
    lat: coarseLocation.lat,
    lng: coarseLocation.lng,
    accuracy_m: Math.max(1000, Math.round(position.coords.accuracy || 0)),
    precision: "approximate",
    home_location: "我的大概位置",
  };

  try {
    const address = await reverseGeocodeLocation(currentLocation);
    applyLocatedAddress(address);
    if (currentLocation.address_confidence === "low") {
      setLocationStatus("暂时只定位到大概区域，请在输入框补充城市、区县或商圈后再生成方案。", "pending");
    } else {
      setLocationStatus(
        `已填入地址：${currentLocation.home_location}。可直接修改；仅用于附近规划，不会发送精确坐标。`,
        "success",
      );
    }
  } catch (error) {
    origin.value = "我的大概位置";
    setLocationStatus("已获取大概坐标，但地址反查失败；可手动补充城市、区县和商圈。", "pending");
  } finally {
    locateBtn.disabled = false;
    locateBtn.textContent = "重新定位";
  }
}

async function reverseGeocodeLocation(location) {
  const response = await fetch("/api/location/reverse-geocode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      coordinates: {
        lat: location.lat,
        lng: location.lng,
      },
      precision: location.precision,
    }),
  });
  const payload = await response.json();
  if (!payload.success) {
    throw new Error(payload.error?.message || "地址反查失败");
  }
  return payload.data;
}

function applyLocatedAddress(address) {
  const formattedAddress = normalizeLocationText(address.formatted_address)
    || normalizeLocationText(`${address.city || ""} ${address.district || ""} ${address.landmark || ""}`);
  const resolvedCity = normalizeLocationText(address.city);

  currentCity = resolvedCity || inferCityFromLocation(formattedAddress) || currentCity || defaultCity;
  origin.value = formattedAddress || "我的大概位置";
  currentLocation = {
    ...currentLocation,
    city: currentCity,
    district: normalizeLocationText(address.district),
    landmark: normalizeLocationText(address.landmark),
    formatted_address: formattedAddress,
    home_location: formattedAddress || "我的大概位置",
    address_source: address.source,
    address_confidence: address.confidence,
  };
}

function syncLocatedAddressEdit() {
  const editedAddress = normalizeLocationText(origin.value);
  const editedCity = inferCityFromLocation(editedAddress);
  if (!editedAddress) {
    currentLocation = null;
    locateBtn.textContent = "定位";
    updateManualLocationStatus();
    return;
  }
  if (editedCity && currentLocation.city && editedCity !== currentLocation.city) {
    currentLocation = null;
    currentCity = editedCity;
    locateBtn.textContent = "定位";
    updateManualLocationStatus();
    return;
  }

  currentCity = editedCity || currentLocation.city || currentCity || defaultCity;
  currentLocation = {
    ...currentLocation,
    city: currentCity,
    formatted_address: editedAddress,
    home_location: editedAddress,
    address_confidence: "edited",
  };
  setLocationStatus("已修改定位地址，将继续使用大概坐标计算距离和路线。", "success");
}

function parseManualLocation(locationValue, cityValue) {
  const location = normalizeLocationText(locationValue);
  const inferredCity = inferCityFromLocation(location);
  const cityName = inferredCity || normalizeLocationText(cityValue) || defaultCity;
  const signalLength = location.replaceAll(" ", "").length;

  if (!location) {
    return {
      valid: false,
      message: manualLocationHelp,
    };
  }
  if (signalLength < 2) {
    return {
      valid: false,
      message: "手动位置至少需要 2 个有效字符，请按城市、区县、商圈或地标输入。",
    };
  }

  const label = cityName && !inferredCity ? `${cityName} ${location}` : location;
  const areaSignals = /(区|县|市|镇|街道|商圈|园区|广场|中心|SOHO|mall|plaza)/i;
  const parts = splitManualLocation(label, cityName);
  return {
    valid: true,
    label,
    city: cityName,
    district: parts.district,
    landmark: parts.landmark,
    format: "city_district_landmark",
    precision: areaSignals.test(label) ? "manual_area" : "manual_landmark",
  };
}

function splitManualLocation(label, cityName) {
  const normalized = normalizeLocationText(label);
  let rest = normalized;
  if (cityName && rest.startsWith(`${cityName}市`)) {
    rest = normalizeLocationText(rest.slice(cityName.length + 1));
  } else if (cityName && rest.startsWith(cityName)) {
    rest = normalizeLocationText(rest.slice(cityName.length));
  }

  const tokens = rest.split(" ").filter(Boolean);
  const districtIndex = tokens.findIndex((token) => /(区|县|市|镇|街道)$/.test(token));
  const district = districtIndex >= 0 ? tokens[districtIndex] : "";
  const landmark = tokens.filter((_, index) => index !== districtIndex).join(" ");
  return { district, landmark: landmark || rest };
}

function inferCityFromLocation(value) {
  const location = normalizeLocationText(value);
  if (!location) return "";

  const knownCity = knownCities.find((cityName) => location.startsWith(cityName));
  if (knownCity) return knownCity;

  const cityMatch = location.match(/^([\u4e00-\u9fa5]{2,8}市)(?:\s|$)/);
  if (cityMatch) return cityMatch[1].replace(/市$/, "");

  return "";
}

function normalizeLocationText(value) {
  return String(value ?? "")
    .replace(/[，,、/|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function updateManualLocationStatus() {
  const manualLocation = parseManualLocation(origin.value, currentCity);
  if (!origin.value.trim()) {
    setLocationStatus(manualLocationHelp, "manual");
    return;
  }
  if (!manualLocation.valid) {
    setLocationStatus(manualLocation.message, "error");
    return;
  }
  currentCity = manualLocation.city;
  setLocationStatus(
    `位置将按：${manualLocation.label} 规划。可手动修改，或点击定位重新填入。`,
    "manual",
  );
}

function setLocationStatus(message, state) {
  locationStatus.textContent = message;
  locationStatus.dataset.state = state;
}

function locationErrorMessage(error) {
  if (error.code === error.PERMISSION_DENIED) {
    return "定位授权被拒绝，将继续使用手动出发地。";
  }
  if (error.code === error.POSITION_UNAVAILABLE) {
    return "暂时无法获取当前位置，请手动输入出发地。";
  }
  if (error.code === error.TIMEOUT) {
    return "定位超时，请重试或手动输入出发地。";
  }
  return "定位失败，请手动输入出发地。";
}

function coarseCoordinates(lat, lng) {
  return {
    lat: Math.round(lat * 100) / 100,
    lng: Math.round(lng * 100) / 100,
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
