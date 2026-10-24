import { Navigate, Outlet, useLocation } from "react-router-dom";
import { isEmailVerified, useAuth } from "../context/AuthContext";

export default function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="loading-state" role="status">Checking your Optiqo session…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  if (!isEmailVerified(user)) return <Navigate to="/verify-email" replace state={{ email: user.email, from: location }} />;
  return <Outlet />;
}
