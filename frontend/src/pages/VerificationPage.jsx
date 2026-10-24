import { CheckCircle2, MailCheck, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Brand from "../components/Brand";
import { Button } from "../components/UI";
import { isEmailVerified, useAuth } from "../context/AuthContext";
import { auth, authErrorMessage } from "../services/auth";

const RESEND_COOLDOWN_SECONDS = 60;
const RESEND_STORAGE_KEY = "optiqo.frontend.verificationResentAt";

export default function VerificationPage() {
  const { user, loading, refreshUser } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(() => {
    try {
      const sentAt = Number(sessionStorage.getItem(RESEND_STORAGE_KEY));
      return Math.max(0, RESEND_COOLDOWN_SECONDS - Math.floor((Date.now() - sentAt) / 1000));
    } catch {
      return 0;
    }
  });
  const email = user?.email || location.state?.email || "your email address";

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  if (loading) return <main className="auth-page"><div className="loading-state" role="status">Checking your verification status…</div></main>;
  if (!user) return <Navigate to="/login" replace state={location.state} />;
  if (isEmailVerified(user)) return <Navigate to={location.state?.from?.pathname || "/app"} replace />;

  async function resend() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await auth.resendVerification(user);
      setMessage(`A new verification link was sent to ${email}.`);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      try {
        sessionStorage.setItem(RESEND_STORAGE_KEY, String(Date.now()));
      } catch {
        // The in-memory cooldown still applies for this page session.
      }
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function checkStatus() {
    setBusy(true);
    setError("");
    try {
      const refreshed = await refreshUser();
      if (isEmailVerified(refreshed)) navigate(location.state?.from?.pathname || "/app", { replace: true });
      else setMessage("Your address is not verified yet. Open the link in the verification email, then check again.");
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    try {
      await auth.signOut();
      navigate("/login", { replace: true });
    } catch (caught) {
      setError(authErrorMessage(caught));
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-orb auth-orb-a" /><div className="auth-orb auth-orb-b" />
      <header className="auth-header"><Brand /><Link to="/" className="nav-signin">Back to home</Link></header>
      <section className="auth-card verification-card">
        <div className="auth-emblem"><MailCheck size={21} /></div>
        <span className="eyebrow">ONE MORE STEP</span>
        <h1>Verify your email</h1>
        <p className="auth-lede">We sent a verification link to <strong>{email}</strong>. Verify the address before opening the private Optiqo workspace.</p>
        {location.state?.notice && <div className="notice notice-warning auth-unavailable" role="status"><ShieldAlert size={17} /><span>Your account was created, but the verification email could not be sent: {location.state.notice} Use the resend action below.</span></div>}
        <div className="notice notice-warning auth-unavailable"><ShieldAlert size={17} /><span>Authentication is temporarily paused. Firebase sign-in is disconnected.</span></div>
        {error && <p className="auth-message" role="alert">{error}</p>}
        {message && <p className="auth-message auth-message-success" role="status">{message}</p>}
        <div className="verification-actions">
          <Button className="button-full" icon={CheckCircle2} onClick={checkStatus} disabled={busy}>I verified my email</Button>
          <Button variant="outline" className="button-full" icon={RefreshCw} onClick={resend} disabled={busy || cooldown > 0}>{cooldown > 0 ? `Resend available in ${cooldown}s` : "Resend verification email"}</Button>
        </div>
        <button type="button" className="auth-demo-link" onClick={signOut} disabled={busy}>Sign out and use another account</button>
      </section>
      <p className="auth-footer">Optiqo · Distribution intelligence for Team VYROX</p>
    </main>
  );
}
