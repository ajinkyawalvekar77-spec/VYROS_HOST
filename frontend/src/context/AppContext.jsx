import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "./AuthContext";

const AppContext = createContext(null);
const RUN_STORAGE_KEY = "optiqo.frontend.runReferences.v2";
const THEME_KEY = "optiqo.frontend.theme.v1";

function runStorageKey(userId) {
  return `${RUN_STORAGE_KEY}:${userId || "anonymous"}`;
}

function readRuns(userId) {
  try {
    const parsed = JSON.parse(localStorage.getItem(runStorageKey(userId)) || "[]");
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch {
    return [];
  }
}

function initialTheme() {
  try {
    return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function AppProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.uid || null;
  const [demoData, setDemoData] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [plan, setPlan] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [runs, setRuns] = useState(() => readRuns(userId));
  const [theme, setTheme] = useState(initialTheme);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Theme remains usable for this session if browser storage is unavailable.
    }
  }, [theme]);

  useEffect(() => {
    setDemoData(null);
    setForecast(null);
    setPlan(null);
    setBacktest(null);
    setRuns(readRuns(userId));
  }, [userId]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notify = useCallback((message, type = "info") => {
    setToast({ message, type, id: Date.now() });
  }, []);

  const rememberRun = useCallback((record) => {
    if (!record?.run_id) return;
    setRuns((current) => {
      const next = [
        {
          run_id: record.run_id,
          operation: record.operation,
          status: record.status || "succeeded",
          created_at: record.created_at || new Date().toISOString(),
        },
        ...current.filter((run) => run.run_id !== record.run_id),
      ].slice(0, 30);
      try {
        localStorage.setItem(runStorageKey(userId), JSON.stringify(next));
      } catch {
        // Run references remain available in memory for this session.
      }
      return next;
    });
  }, [userId]);

  const clearUserData = useCallback(() => {
    setDemoData(null);
    setForecast(null);
    setPlan(null);
    setBacktest(null);
    setRuns([]);
    try {
      localStorage.removeItem(runStorageKey(userId));
    } catch {
      // In-memory state is cleared even when storage is unavailable.
    }
  }, [userId]);

  const value = useMemo(
    () => ({
      demoData,
      setDemoData,
      forecast,
      setForecast,
      plan,
      setPlan,
      backtest,
      setBacktest,
      runs,
      rememberRun,
      clearUserData,
      theme,
      toggleTheme: () => setTheme((current) => (current === "light" ? "dark" : "light")),
      toast,
      notify,
    }),
    [demoData, forecast, plan, backtest, runs, rememberRun, clearUserData, theme, toast, notify],
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used within AppProvider.");
  return context;
}
