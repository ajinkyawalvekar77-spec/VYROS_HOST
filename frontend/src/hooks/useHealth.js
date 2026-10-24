import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api";

export function useHealth() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const refresh = useCallback(async (signal) => {
    setLoading(true);
    try {
      const result = await api.getHealth({ signal, timeoutMs: 8000 });
      setHealth(result);
      setError(null);
    } catch (caught) {
      setHealth(null);
      setError(caught);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    const interval = window.setInterval(() => refresh(), 30_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refresh]);
  return { health, loading, error, refresh };
}
