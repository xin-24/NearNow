import { useState, useCallback, useRef } from "react";
import { useTheme } from "./hooks/useTheme";
import { useAuth } from "./hooks/useAuth";
import { useLocation } from "./hooks/useLocation";
import { Ambient } from "./components/Ambient";
import { Header } from "./components/Header";
import { LoginView } from "./views/LoginView";
import { InputView } from "./views/InputView";
import { AnalyzingView } from "./views/AnalyzingView";
import { ProposalView } from "./views/ProposalView";
import { ExecutingView } from "./views/ExecutingView";
import { SuccessView } from "./views/SuccessView";
import { ErrorView } from "./views/ErrorView";
import { generatePlan, confirmPlan, createAbortController, isAborted } from "./api/client";
import { parseCompanions, selectedRouteMode, formatCompanionLine } from "./utils/route";
import type { Plan, ExecutionResponse } from "./api/types";
import styles from "./App.module.css";

type View = "login" | "input" | "analyzing" | "proposal" | "executing" | "success" | "error";

export function App() {
  const { toggle: toggleTheme } = useTheme();
  const { user, loading, login, logout, loadCompanions } = useAuth();
  const location = useLocation();

  const [currentView, setCurrentView] = useState<View>(loading ? "login" : "login");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [execution, setExecution] = useState<ExecutionResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [defaultCompanions, setDefaultCompanions] = useState("");
  const [lastGoal, setLastGoal] = useState("");
  const [lastCompanions, setLastCompanions] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const handleLogin = useCallback(
    async (username: string, password: string, displayName: string) => {
      await login(username, password, displayName);
      const companions = await loadCompanions();
      if (companions.length) {
        setDefaultCompanions(companions.map(formatCompanionLine).join("\n"));
      }
      setCurrentView("input");
    },
    [login, loadCompanions],
  );

  const handleLogout = useCallback(async () => {
    await logout();
    setPlan(null);
    setExecution(null);
    setDefaultCompanions("");
    setCurrentView("login");
  }, [logout]);

  const handlePlan = useCallback(
    async (goal: string, companionsText: string) => {
      if (!user) {
        setCurrentView("login");
        return;
      }
      if (!goal.trim()) return;

      const userContext = buildUserContext(location);
      if ("error" in userContext) {
        location.updateOrigin(location.origin);
        return;
      }

      setLastGoal(goal);
      setLastCompanions(companionsText);
      setPlan(null);
      setExecution(null);
      setCurrentView("analyzing");

      const controller = createAbortController();
      abortRef.current = controller;

      try {
        const data = await generatePlan(goal, "real", userContext, parseCompanions(companionsText), controller.signal);
        setPlan(data);
        setCurrentView("proposal");
      } catch (err) {
        if (isAborted(err)) {
          setCurrentView("input");
          return;
        }
        setErrorMessage(err instanceof Error ? err.message : "规划失败");
        setCurrentView("error");
      } finally {
        abortRef.current = null;
      }
    },
    [user, location],
  );

  const handleConfirm = useCallback(async (selectedPlan?: Plan) => {
    const planToConfirm = selectedPlan || plan;
    if (!planToConfirm) return;
    setCurrentView("executing");

    const controller = createAbortController();
    abortRef.current = controller;

    try {
      const data = await confirmPlan(
        planToConfirm.plan_id,
        planToConfirm.pending_actions.map((a) => a.action_id),
        selectedRouteMode(planToConfirm),
        controller.signal,
      );
      setExecution(data);
      setCurrentView("success");
    } catch (err) {
      if (isAborted(err)) {
        setCurrentView("proposal");
        return;
      }
      setErrorMessage(err instanceof Error ? err.message : "执行失败");
      setCurrentView("error");
    } finally {
      abortRef.current = null;
    }
  }, [plan]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const handleRouteChange = useCallback((updatedPlan: Plan) => {
    setPlan(updatedPlan);
  }, []);

  const handlePlanUpdate = useCallback((updatedPlan: Plan) => {
    setPlan(updatedPlan);
  }, []);

  const handleNewPlan = useCallback(() => {
    setPlan(null);
    setExecution(null);
    setCurrentView("input");
  }, []);

  const handleEdit = useCallback(() => {
    setCurrentView("input");
  }, []);

  const handleBack = useCallback(() => {
    setCurrentView("input");
  }, []);

  return (
    <>
      <Ambient />
      <Header user={user} onLogout={handleLogout} onToggleTheme={toggleTheme} />
      <main className={styles.shell}>
        {currentView === "login" && <LoginView onLogin={handleLogin} />}
        {currentView === "input" && (
          <InputView
            defaultGoal={lastGoal || "今天下午是空的，想和老婆孩子、朋友出去玩几个小时，别离家太远，帮我安排一下。"}
            defaultCompanions={lastCompanions || defaultCompanions}
            origin={location.origin}
            locationStatus={location.status}
            locating={location.locating}
            onOriginChange={location.updateOrigin}
            onLocate={location.locate}
            onPlan={handlePlan}
          />
        )}
        {currentView === "analyzing" && <AnalyzingView onCancel={handleCancel} />}
        {currentView === "proposal" && plan && (
          <ProposalView
            plan={plan}
            onEdit={handleEdit}
            onConfirm={handleConfirm}
            onRouteChange={handleRouteChange}
            onPlanUpdate={handlePlanUpdate}
          />
        )}
        {currentView === "executing" && plan && (
          <ExecutingView actions={plan.pending_actions} onCancel={handleCancel} />
        )}
        {currentView === "success" && execution && <SuccessView result={execution} onNewPlan={handleNewPlan} />}
        {currentView === "error" && <ErrorView message={errorMessage} onBack={handleBack} />}
      </main>
    </>
  );
}

function buildUserContext(loc: ReturnType<typeof useLocation>): Record<string, unknown> {
  if (loc.locationData) {
    return {
      home_location: loc.locationData.home_location || loc.origin || "我的大概位置",
      city: loc.locationData.city || loc.city,
      coordinates: { lat: loc.locationData.lat, lng: loc.locationData.lng },
      location_permission_granted: true,
      location_source: "browser",
      accuracy_m: loc.locationData.accuracy_m,
      precision: loc.locationData.precision,
      district: loc.locationData.district,
      landmark: loc.locationData.landmark,
      formatted_address: loc.locationData.formatted_address,
      address_source: loc.locationData.address_source,
      address_confidence: loc.locationData.address_confidence,
    };
  }

  const manualLocation = parseManualLocation(loc.origin, loc.city);
  if (!manualLocation.valid) {
    return { error: manualLocation.message };
  }

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

function parseManualLocation(locationValue: string, cityValue: string) {
  const location = normalizeLocationText(locationValue);
  const inferredCity = inferCityFromLocation(location);
  const cityName = inferredCity || normalizeLocationText(cityValue) || "北京";
  const signalLength = location.replace(/ /g, "").length;

  if (!location) {
    return { valid: false, message: "出发位置格式：城市 + 区/县 + 商圈/地标。可手动输入，也可定位后直接修改。" };
  }
  if (signalLength < 2) {
    return { valid: false, message: "手动位置至少需要 2 个有效字符，请按城市、区县、商圈或地标输入。" };
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

function splitManualLocation(label: string, cityName: string) {
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

function normalizeLocationText(value: string): string {
  return String(value ?? "").replace(/[，,、/|]+/g, " ").replace(/\s+/g, " ").trim();
}

const knownCities = [
  "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "天津",
  "南京", "苏州", "武汉", "西安", "厦门", "长沙", "郑州", "青岛",
  "纽约", "旧金山",
];

function inferCityFromLocation(value: string): string {
  const location = normalizeLocationText(value);
  if (!location) return "";
  const knownCity = knownCities.find((city) => location.startsWith(city));
  if (knownCity) return knownCity;
  const cityMatch = location.match(/^([一-龥]{2,8}市)(?:\s|$)/);
  if (cityMatch) return cityMatch[1].replace(/市$/, "");
  return "";
}
