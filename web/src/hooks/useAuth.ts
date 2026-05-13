import { useState, useEffect, useCallback } from "react";
import type { User } from "../api/types";
import { checkSession, login as apiLogin, logout as apiLogout, loadCompanions as apiLoadCompanions } from "../api/client";

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkSession()
      .then((data) => {
        if (data.authenticated && data.user) {
          setUser(data.user);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string, displayName: string) => {
    const data = await apiLogin(username, password, displayName);
    setUser(data.user);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const loadCompanions = useCallback(async () => {
    try {
      const data = await apiLoadCompanions();
      return data;
    } catch {
      return [];
    }
  }, []);

  return { user, loading, login, logout, loadCompanions };
}
