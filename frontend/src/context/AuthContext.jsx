import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { auth } from "../services/auth";

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user] = useState(
    auth.localDevelopmentMode
      ? {
        uid: "local-development",
        email: "local@optiqo.test",
        displayName: "Local development",
        emailVerified: true,
      }
      : null,
  );
  const [loading] = useState(false);
  const [authError] = useState(null);

  const refreshUser = useCallback(async () => {
    return auth.refreshUser();
  }, []);

  const value = useMemo(
    () => ({ user, loading, authError, configured: auth.localDevelopmentMode, refreshUser }),
    [user, loading, authError, refreshUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}

export function isEmailVerified(user) {
  if (!user) return false;
  return user.emailVerified === true;
}
