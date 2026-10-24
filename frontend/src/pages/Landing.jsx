import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  Boxes,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  CircleHelp,
  Database,
  Menu,
  PackageCheck,
  ShieldCheck,
  Sparkles,
  Truck,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import Brand from "../components/Brand";

const capabilities = [
  {
    icon: Database,
    title: "Data validation",
    text: "Catch missing, invalid, and inconsistent records before they reach forecasting or planning.",
    to: "/app/data",
    action: "Review data quality",
  },
  {
    icon: ChartNoAxesCombined,
    title: "Demand forecasting",
    text: "Explore model-generated demand by SKU and destination, with model details and uncertainty when available.",
    to: "/app",
    action: "Explore forecasts",
  },
  {
    icon: Boxes,
    title: "Inventory risk intelligence",
    text: "Inspect supported stock, expiry, and unmet-demand indicators without an unexplained composite score.",
    to: "/app/risk",
    action: "Review risk indicators",
  },
  {
    icon: Truck,
    title: "Distribution optimization",
    text: "Build allocation proposals against eligible lanes, available inventory, capacity, and shelf-life rules.",
    to: "/app/plan",
    action: "Explore planning",
  },
  {
    icon: ShieldCheck,
    title: "Explainable recommendations",
    text: "Review solver status, independent checks, and the evidence behind an allocation proposal.",
    to: "/app/plan",
    action: "See plan evidence",
  },
  {
    icon: PackageCheck,
    title: "Backtesting & evaluation",
    text: "Compare supported policies against chronological demand using documented simulation measures.",
    to: "/app/backtest",
    action: "Explore evaluation",
  },
];

const workflow = [
  { title: "Load data", detail: "Start with your dataset or a reproducible synthetic example." },
  { title: "Validate", detail: "Check required tables, values, and business relationships." },
  { title: "Forecast", detail: "Estimate demand over the engine-supported horizon." },
  { title: "Assess risk", detail: "Review stock, expiry, and demand exposure from available inputs." },
  { title: "Optimize", detail: "Propose movements that respect routes and operational constraints." },
  { title: "Evaluate", detail: "Replay policies against held-out demand with documented assumptions." },
  { title: "Export", detail: "Inspect persisted run evidence and download its results." },
];

function PreviewChart() {
  return (
    <div className="preview-card">
      <div className="preview-top">
        <div><span className="preview-dot" /><span>NETWORK OVERVIEW</span></div>
        <span className="preview-label">ILLUSTRATIVE · SYNTHETIC</span>
      </div>
      <div className="preview-heading">
        <div><span className="preview-muted">Demand outlook</span><strong>Historical &amp; forecast view</strong></div>
        <span className="preview-pill">Concept preview</span>
      </div>
      <div className="preview-legend">
        <span><i className="legend-line legend-history" /> Historical observations</span>
        <span><i className="legend-line legend-forecast" /> Illustrative forecast</span>
      </div>
      <svg className="preview-chart" viewBox="0 0 520 170" role="img" aria-label="Illustrative synthetic historical demand and forecast trend">
        <defs>
          <linearGradient id="previewFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#5278ee" stopOpacity=".18" />
            <stop offset="100%" stopColor="#5278ee" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[30, 68, 106, 144].map((y) => <line key={y} x1="30" x2="510" y1={y} y2={y} stroke="#e9edf5" strokeDasharray="4 6" />)}
        <path d="M30 119 C65 112 77 93 105 99 S154 121 180 101 S224 62 254 76 S304 102 328 82 S367 47 393 64 L393 150 L30 150Z" fill="url(#previewFill)" />
        <path d="M30 119 C65 112 77 93 105 99 S154 121 180 101 S224 62 254 76 S304 102 328 82 S367 47 393 64" fill="none" stroke="#5278ee" strokeWidth="3" strokeLinecap="round" />
        <path d="M393 64 C421 85 442 88 468 53 S497 54 510 38" fill="none" stroke="#239e91" strokeWidth="3" strokeLinecap="round" strokeDasharray="6 6" />
        <line x1="393" x2="393" y1="39" y2="148" stroke="#aab4c8" strokeDasharray="3 5" />
        {[["M", "01"], ["T", "02"], ["W", "03"], ["T", "04"], ["F", "05"], ["S", "06"], ["S", "07"]].map(([day, num], i) => <text key={i} x={47 + i * 73} y="166" textAnchor="middle" fill="#8893a7" fontSize="10">{day} {num}</text>)}
      </svg>
      <div className="preview-bottom">
        <div><span className="risk-indicator risk-amber" /><span>Expiry exposure</span><strong>Shown when supported</strong></div>
        <div className="preview-allocation"><span><Boxes size={15} /> Allocation</span><strong>Independent check available</strong></div>
      </div>
      <span className="preview-footnote">Illustrative interface only — no live forecast or operational result is shown here.</span>
    </div>
  );
}

function WorkspacePreview() {
  return (
    <div className="showcase-frame" aria-label="Illustrative Optiqo application preview">
      <div className="showcase-window-bar">
        <span className="showcase-window-dots"><i /><i /><i /></span>
        <span>Optiqo · Decision workspace</span>
        <span className="showcase-window-tag"><span /> SYNTHETIC PREVIEW</span>
      </div>
      <div className="showcase-window-body">
        <aside className="showcase-sidebar" aria-hidden="true">
          <span className="showcase-side-brand"><Boxes size={15} /> optiqo.</span>
          <span className="showcase-side-label">WORKSPACE</span>
          <span className="showcase-side-item showcase-side-active"><ChartNoAxesCombined size={14} /> Overview</span>
          <span className="showcase-side-item"><Database size={14} /> Data validation</span>
          <span className="showcase-side-item"><Boxes size={14} /> Risk overview</span>
          <span className="showcase-side-item"><Truck size={14} /> Distribution plan</span>
        </aside>
        <div className="showcase-dashboard">
          <div className="showcase-dashboard-head">
            <div><span>NETWORK INTELLIGENCE</span><strong>From data to decisions</strong></div>
            <span className="showcase-health"><i /> API status checked live in workspace</span>
          </div>
          <div className="showcase-stage-grid">
            <div className="showcase-stage">
              <span className="showcase-stage-icon stage-blue"><Database size={16} /></span>
              <span className="showcase-stage-label">01 · INPUT QUALITY</span>
              <strong>Validate the dataset</strong>
              <small>Inspect required tables and business rules.</small>
              <span className="showcase-stage-link">Data validation <ArrowUpRight size={12} /></span>
            </div>
            <div className="showcase-stage">
              <span className="showcase-stage-icon stage-violet"><ChartNoAxesCombined size={16} /></span>
              <span className="showcase-stage-label">02 · DEMAND OUTLOOK</span>
              <strong>Forecast from history</strong>
              <small>View engine output, model, and supported intervals.</small>
              <span className="showcase-stage-link">Forecast view <ArrowUpRight size={12} /></span>
            </div>
            <div className="showcase-stage">
              <span className="showcase-stage-icon stage-teal"><Truck size={16} /></span>
              <span className="showcase-stage-label">03 · DISTRIBUTION</span>
              <strong>Plan with constraints</strong>
              <small>Review proposed movements and verification.</small>
              <span className="showcase-stage-link">Plan workspace <ArrowUpRight size={12} /></span>
            </div>
          </div>
          <div className="showcase-bottom-note"><ShieldCheck size={15} /><span>Actual forecasts, risk measures, and plans appear after a real backend run.</span></div>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);

  return (
    <main className="landing-page">
      <header className="marketing-nav">
        <Brand />
        <nav aria-label="Main navigation" className="marketing-links">
          <a href="#product">Product</a>
          <a href="#capabilities">Capabilities</a>
          <a href="#how-it-works">How it works</a>
          <a href="#about">About</a>
        </nav>
        <div className="marketing-actions">
          <Link to="/login" className="nav-signin">Sign in</Link>
          <Link to="/app" className="button button-primary">Explore workspace <ArrowRight size={15} /></Link>
        </div>
        <button
          type="button"
          className="marketing-menu-toggle"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={menuOpen}
          aria-controls="marketing-mobile-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        {menuOpen && (
          <nav className="marketing-mobile-nav" id="marketing-mobile-nav" aria-label="Mobile navigation">
            <a href="#product" onClick={closeMenu}>Product <ArrowRight size={15} /></a>
            <a href="#capabilities" onClick={closeMenu}>Capabilities <ArrowRight size={15} /></a>
            <a href="#how-it-works" onClick={closeMenu}>How it works <ArrowRight size={15} /></a>
            <a href="#about" onClick={closeMenu}>About <ArrowRight size={15} /></a>
            <Link to="/login" onClick={closeMenu}>Sign in <ArrowRight size={15} /></Link>
            <Link to="/app" className="mobile-nav-cta" onClick={closeMenu}>Explore workspace <ArrowRight size={15} /></Link>
          </nav>
        )}
      </header>

      <section className="hero-section" id="product">
        <div className="hero-orb hero-orb-one" />
        <div className="hero-orb hero-orb-two" />
        <div className="hero-copy">
          <span className="hero-kicker"><Sparkles size={14} /> AI-POWERED DISTRIBUTION INTELLIGENCE</span>
          <h1>Turn distribution data into <span>smarter decisions.</span></h1>
          <p>Forecast demand, uncover inventory risks, and build explainable distribution plans with an integrated intelligence and optimization platform for FMCG networks.</p>
          <div className="hero-actions">
            <Link to="/app" className="button button-primary button-large">Explore the platform <ArrowRight size={17} /></Link>
            <a href="#how-it-works" className="button button-outline button-large">View how it works <ArrowDownRight size={16} /></a>
          </div>
          <div className="hero-proof"><ShieldCheck size={16} /><span>Grounded in your data, operational constraints, and independent checks.</span></div>
          <div className="hero-trust-row">
            <span><Check size={13} /> Constraint-aware plans</span>
            <span><Check size={13} /> Transparent evaluation</span>
          </div>
        </div>
        <div className="hero-visual"><PreviewChart /></div>
        <a className="scroll-cue" href="#capabilities"><span>Discover the platform</span><ChevronDown size={15} /></a>
      </section>

      <section className="section-wrap capabilities-section" id="capabilities">
        <div className="section-heading">
          <span className="eyebrow">One connected intelligence platform</span>
          <h2>Better distribution starts<br />with a clearer picture.</h2>
          <p>Move from trusted inputs to measured decisions in a workflow built for the realities of FMCG distribution.</p>
        </div>
        <div className="capability-grid">
          {capabilities.map(({ icon: Icon, title, text, to, action }, index) => (
            <Link className="capability-card" key={title} to={to}>
              <span className="capability-icon"><Icon size={19} /></span>
              <span className="capability-index">0{index + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
              <span className="capability-action">{action}<ArrowUpRight size={14} /></span>
            </Link>
          ))}
        </div>
      </section>

      <section className="showcase-section" aria-labelledby="showcase-title">
        <div className="section-wrap showcase-layout">
          <div className="showcase-copy">
            <span className="eyebrow">A workspace made for decisions</span>
            <h2 id="showcase-title">See the whole journey.<br />Keep every result grounded.</h2>
            <p>Validate data, inspect model outputs, compare risk indicators, and review allocation evidence in one connected workspace.</p>
            <ul className="showcase-checklist">
              <li><BadgeCheck size={17} /><span><strong>Know what you are viewing</strong>Historical demand, forecasts, plans, and simulated outcomes stay distinct.</span></li>
              <li><BadgeCheck size={17} /><span><strong>Understand every recommendation</strong>Inspect solver results, operating constraints, and verification.</span></li>
              <li><BadgeCheck size={17} /><span><strong>Evaluate with context</strong>Compare supported policies using documented inputs and assumptions.</span></li>
            </ul>
            <Link to="/app" className="text-link showcase-link">Explore the decision workspace <ArrowRight size={16} /></Link>
          </div>
          <WorkspacePreview />
        </div>
      </section>

      <section className="workflow-section" id="how-it-works">
        <div className="section-wrap">
          <div className="workflow-intro">
            <span className="eyebrow">How it works</span>
            <h2>A connected path from<br />input to outcome.</h2>
            <p>Each step uses the backend's actual data, forecasting, optimization, and evaluation workflows. Operations run when you request them; failures and unsupported measures remain visible.</p>
          </div>
          <div className="workflow-steps">
            {workflow.map((step, index) => (
              <div className="workflow-step" key={step.title}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step.title}</strong>
                {index < workflow.length - 1 && <ArrowRight size={15} aria-hidden="true" />}
              </div>
            ))}
          </div>
          <div className="workflow-details">
            {workflow.map((step, index) => (
              <article key={step.title}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{step.title}</strong><p>{step.detail}</p></div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="transparency-section" aria-label="Trust and transparency">
        <div className="section-wrap transparency-layout">
          <div><span className="eyebrow">Built for clarity, not black boxes</span><h2>Every insight has a source.<br />Every assumption stays visible.</h2></div>
          <div className="transparency-points">
            <div><Database size={18} /><span><strong>Know the provenance</strong>Demo data is identified as synthetic; uploaded data remains user-supplied.</span></div>
            <div><ChartNoAxesCombined size={18} /><span><strong>See model outputs for what they are</strong>Fallback models and unavailable measures are reported honestly.</span></div>
            <div><ShieldCheck size={18} /><span><strong>Verify before you act</strong>Plans are accompanied by solver status and independent checks.</span></div>
          </div>
        </div>
      </section>

      <section className="section-wrap about-section" id="about">
        <div className="about-symbol"><Boxes size={30} /></div>
        <div>
          <span className="eyebrow">Built for the complexity behind every delivery</span>
          <h2>Make every movement<br />more intentional.</h2>
          <p>Optiqo brings data validation, forecasting, inventory allocation, independent checks, and simulation into one explainable workspace for distribution teams.</p>
          <Link to="/app" className="text-link">Explore the workspace <ArrowRight size={16} /></Link>
        </div>
        <div className="team-card">
          <span className="team-label">BUILT BY</span>
          <strong>Team VYROX</strong>
          <span>THREE MINDS.<br />ONE VISION. NO LIMITS.</span>
          <CircleHelp size={17} aria-hidden="true" />
        </div>
      </section>

      <footer className="marketing-footer">
        <Brand />
        <span>Turn distribution data into smarter decisions.</span>
        <div><Link to="/login">Sign in</Link><span>© {new Date().getFullYear()} Optiqo · Team VYROX</span></div>
      </footer>
    </main>
  );
}
