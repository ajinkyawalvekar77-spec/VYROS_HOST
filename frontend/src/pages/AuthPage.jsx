import { Eye, EyeOff, LockKeyhole, Mail, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Brand from "../components/Brand";
import { Button } from "../components/UI";
import { isEmailVerified, useAuth } from "../context/AuthContext";
import { auth, authErrorMessage } from "../services/auth";

export default function AuthPage({ mode = "login" }) {
  const isSignup = mode === "signup";
  const isForgot = mode === "forgot";
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("error");
  const [busy, setBusy] = useState(false);
  const [terms, setTerms] = useState(false);
  const location = useLocation();
  const { user } = useAuth();
  const returnPath = location.state?.from?.pathname || "/app";
  const title = isSignup ? "Create your workspace" : isForgot ? "Reset your password" : "Welcome back";

  if (auth.localDevelopmentMode) return <Navigate to={returnPath} replace />;
  if (!isSignup && !isForgot && user && isEmailVerified(user)) return <Navigate to={returnPath} replace />;

  async function submit(event) {
    event.preventDefault();
    setMessage(authErrorMessage({ code: "auth/temporarily-disabled" }));
    setMessageType("error");
  }

  function signInGoogle() {
    setMessage(authErrorMessage({ code: "auth/temporarily-disabled" }));
    setMessageType("error");
  }

  return (
    <main className="auth-page">
      <div className="auth-orb auth-orb-a" /><div className="auth-orb auth-orb-b" />
      <header className="auth-header"><Brand /><Link to="/" className="nav-signin">Back to home</Link></header>
      <section className="auth-card">
        <div className="auth-emblem">{isForgot ? <Mail size={20} /> : <LockKeyhole size={20} />}</div>
        <span className="eyebrow">{isSignup ? "GET STARTED WITH OPTIQO" : isForgot ? "ACCOUNT RECOVERY" : "YOUR DISTRIBUTION WORKSPACE"}</span>
        <h1>{title}</h1>
        <p className="auth-lede">{isSignup ? "Create an account to get started with your team." : isForgot ? "We'll send a reset link if an account matches that address." : "Sign in to continue to your decision workspace."}</p>

        <div className="notice notice-warning auth-unavailable"><ShieldAlert size={17} /><span>Authentication is temporarily paused. Firebase sign-in is disconnected, and workspace access remains protected until another sign-in method is configured.</span></div>

        <form onSubmit={submit} className="auth-form">
          {isSignup && (
            <label>Full name
              <input name="fullName" autoComplete="name" placeholder="Your name" required minLength={2} />
            </label>
          )}
          <label>Email address
            <input name="email" type="email" autoComplete="email" placeholder="you@company.com" required />
          </label>
          {!isForgot && <label>Password
            <span className="password-input">
              <input name="password" type={showPassword ? "text" : "password"} autoComplete={isSignup ? "new-password" : "current-password"} placeholder={isSignup ? "At least 12 characters" : "Your password"} required minLength={isSignup ? 12 : 1} />
              <button type="button" className="password-toggle" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((value) => !value)}>
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </span>
          </label>}
          {isSignup && (
            <>
              <label>Confirm password
                <span className="password-input">
                  <input name="confirmPassword" type={showConfirmation ? "text" : "password"} autoComplete="new-password" placeholder="Enter password again" required minLength={12} />
                  <button type="button" className="password-toggle" aria-label={showConfirmation ? "Hide confirmation" : "Show confirmation"} onClick={() => setShowConfirmation((value) => !value)}>
                    {showConfirmation ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
              <label className="terms-check"><input type="checkbox" checked={terms} onChange={(event) => setTerms(event.target.checked)} /> <span>I acknowledge the terms and privacy notice.</span></label>
            </>
          )}
          {!isSignup && !isForgot && <Link to="/forgot-password" className="auth-forgot-link">Forgot password?</Link>}
          {message && <p className={`auth-message ${messageType === "success" ? "auth-message-success" : ""}`} role={messageType === "success" ? "status" : "alert"}>{message}</p>}
          <Button type="submit" className="button-full" disabled={busy}>{busy ? "Please wait…" : isSignup ? "Create account" : isForgot ? "Send reset link" : "Sign in"}</Button>
        </form>
        {!isSignup && !isForgot && <>
          <div className="auth-divider"><span>or</span></div>
          <Button variant="outline" className="button-full google-signin" disabled={busy} onClick={signInGoogle}><span className="google-mark" aria-hidden="true">G</span>Continue with Google</Button>
        </>}
        <div className="auth-switch">
          {isForgot ? "Remember your password?" : isSignup ? "Already have an account?" : "New to Optiqo?"}{" "}
          <Link to={isSignup || isForgot ? "/login" : "/signup"} state={location.state}>{isSignup || isForgot ? "Sign in" : "Create an account"}</Link>
        </div>
      </section>
      <p className="auth-footer">Optiqo · Distribution intelligence for Team VYROX</p>
    </main>
  );
}
