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

initTheme();
renderStepList(analyzingSteps, analyzingCopy, 0);
renderStepList(executingSteps, [], 0);
updateManualLocationStatus();

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
        mode: "mock",
        user_context: userContext,
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
    coordinates: { lat: 39.9957, lng: 116.4813 },
    location_permission_granted: false,
    location_source: "manual",
    manual_location_format: manualLocation.format,
    precision: manualLocation.precision,
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
  return {
    valid: true,
    label,
    city: cityName,
    format: "city_district_landmark",
    precision: areaSignals.test(label) ? "manual_area" : "manual_landmark",
  };
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
