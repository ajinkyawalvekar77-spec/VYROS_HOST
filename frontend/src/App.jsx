import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

const AppLayout = lazy(() => import("./layouts/AppLayout"));
const AuthPage = lazy(() => import("./pages/AuthPage"));
const Landing = lazy(() => import("./pages/Landing"));
const BacktestPage = lazy(() => import("./pages/BacktestPage"));
const DataPage = lazy(() => import("./pages/DataPage"));
const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const PlanPage = lazy(() => import("./pages/PlanPage"));
const RecommendationPage = lazy(() => import("./pages/RecommendationPage"));
const RiskPage = lazy(() => import("./pages/RiskPage"));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage"));
const RunsPage = lazy(() => import("./pages/RunsPage"));
const VerificationPage = lazy(() => import("./pages/VerificationPage"));
const ProtectedRoute = lazy(() => import("./routing/ProtectedRoute"));

export default function App() {
  return (
    <Suspense fallback={<div className="loading-state" role="status">Loading Optiqo…</div>}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<AuthPage />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route path="/forgot-password" element={<AuthPage mode="forgot" />} />
        <Route path="/verify-email" element={<VerificationPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/app" element={<AppLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="data" element={<DataPage />} />
            <Route path="risk" element={<RiskPage />} />
            <Route path="plan" element={<PlanPage />} />
            <Route path="backtest" element={<BacktestPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="recommendations/:runId" element={<RecommendationPage />} />
            <Route path="*" element={<Navigate to="/app" replace />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
