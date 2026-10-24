import {
  Activity,
  ArrowUpRight,
  Boxes,
  ChartNoAxesCombined,
  ChevronDown,
  ClipboardCheck,
  Compass,
  LogOut,
  Menu,
  Moon,
  PackageCheck,
  Settings2,
  Sun,
  Truck,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import Brand from "../components/Brand";
import { ApiStatus, IconButton, ToastHost } from "../components/UI";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { useHealth } from "../hooks/useHealth";

const navigation = [
  { label: "Overview", to: "/app", icon: ChartNoAxesCombined, end: true },
  { label: "Data validation", to: "/app/data", icon: ClipboardCheck },
  { label: "Risk overview", to: "/app/risk", icon: Compass },
  { label: "Distribution plan", to: "/app/plan", icon: Truck },
  { label: "Backtesting", to: "/app/backtest", icon: Activity },
  { label: "Run history", to: "/app/runs", icon: PackageCheck },
];

const pageLabels = [
  ["/app/data", "Data validation"],
  ["/app/risk", "Risk overview"],
  ["/app/plan", "Distribution plan"],
  ["/app/backtest", "Backtesting"],
  ["/app/runs", "Run history"],
  ["/app/recommendations/", "Recommendation detail"],
];

export default function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggleTheme, demoData, notify, toast, clearUserData } = useApp();
  const { user } = useAuth();
  const { health, loading, refresh } = useHealth();
  const location = useLocation();
  const navigate = useNavigate();
  const title = pageLabels.find(([path]) => location.pathname.startsWith(path))?.[1] || "Overview";
  const displayName = user?.displayName || user?.email || "Optiqo user";

  async function handleSignOut() {
    clearUserData();
    navigate("/login", { replace: true });
  }

  const Sidebar = ({ mobile = false }) => (
    <div className={`sidebar-inner ${mobile ? "sidebar-mobile-inner" : ""}`}>
      <div className="sidebar-brand"><Brand /></div>
      <div className="workspace-select">
        <span className="workspace-mark"><Boxes size={16} /></span>
        <span><strong>VYROX workspace</strong><small>Distribution intelligence</small></span>
        <ChevronDown size={14} />
      </div>
      <div className="nav-caption">WORKSPACE</div>
      <nav className="side-nav" aria-label="Workspace navigation">
        {navigation.map(({ label, to, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)} className={({ isActive }) => `side-link ${isActive ? "side-link-active" : ""}`}>
            <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
            {label === "Data validation" && demoData && <span className="nav-ready-dot" />}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-bottom-note">
        <span className="note-icon"><Settings2 size={15} /></span>
        <div><strong>Decision support</strong><span>Verify every recommendation</span></div>
        <ArrowUpRight size={14} />
      </div>
      <div className="sidebar-user">
        <div className="avatar">{displayName.charAt(0).toUpperCase()}</div>
        <div><strong>{displayName}</strong><span>{user?.email || "Optiqo workspace"}</span></div>
        {mobile && <button type="button" className="sidebar-logout" onClick={handleSignOut}>Sign out <LogOut size={15} /></button>}
      </div>
    </div>
  );

  return (
    <div className="app-shell">
      <aside className="app-sidebar"><Sidebar /></aside>
      {mobileOpen && <div className="mobile-nav-backdrop" onClick={() => setMobileOpen(false)} role="presentation"><aside className="mobile-nav-panel" onClick={(event) => event.stopPropagation()}><IconButton label="Close menu" onClick={() => setMobileOpen(false)}><X size={18} /></IconButton><Sidebar mobile /></aside></div>}
      <div className="app-main">
        <header className="app-topbar">
          <div className="topbar-left">
            <IconButton label="Open navigation" className="mobile-menu-button" onClick={() => setMobileOpen(true)}><Menu size={19} /></IconButton>
            <div className="breadcrumbs"><span>Workspace</span><span className="breadcrumb-sep">/</span><strong>{title}</strong></div>
          </div>
          <div className="topbar-right">
            <ApiStatus health={health} loading={loading} />
            <IconButton label="Refresh API status" onClick={() => refresh()}><Activity size={17} /></IconButton>
            <IconButton label={`Switch to ${theme === "light" ? "dark" : "light"} mode`} onClick={toggleTheme}>{theme === "light" ? <Moon size={17} /> : <Sun size={17} />}</IconButton>
            <div className="topbar-account"><span className="avatar avatar-small">{displayName.charAt(0).toUpperCase()}</span><span className="profile-name">{displayName}</span><IconButton label="Sign out" onClick={handleSignOut}><LogOut size={16} /></IconButton></div>
          </div>
        </header>
        {!health?.engine_ready && !loading && <div className="connection-banner" role="status">Backend or engine unavailable. Live operations will show their actual connection error. <a href="/#how-it-works" onClick={(event) => { event.preventDefault(); navigate("/"); }}>Connection help</a></div>}
        <main className="app-content"><Outlet context={{ health, loading, refresh }} /></main>
        <footer className="app-footer"><span>Optiqo <b>·</b> Decision support, not autopilot</span><span>{demoData?.synthetic ? "Synthetic demo dataset loaded" : "No dataset loaded"}</span></footer>
      </div>
      <ToastHost toast={toast} />
    </div>
  );
}
