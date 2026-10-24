import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { AppProvider } from "../context/AppContext";
import { AuthProvider } from "../context/AuthContext";
import { auth } from "../services/auth";
import App from "../App";

afterEach(cleanup);

function CurrentPath() {
  const location = useLocation();
  return <output data-testid="current-path">{location.pathname}</output>;
}

describe("Optiqo frontend entry points", () => {
  it("renders the public product landing with working navigation targets", async () => {
    render(
      <AuthProvider><AppProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </AppProvider></AuthProvider>,
    );
    expect(await screen.findByRole("heading", { name: /turn distribution data into smarter decisions/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /explore the platform/i })).toHaveAttribute("href", "/app");
    expect(screen.getAllByRole("link", { name: /sign in/i }).some((link) => link.getAttribute("href") === "/login")).toBe(true);
    expect(screen.getByText(/illustrative · synthetic/i)).toBeInTheDocument();
  });

  it("opens the workspace directly in local development without a sign-in page", async () => {
    render(
      <AuthProvider><AppProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <App />
          <CurrentPath />
        </MemoryRouter>
      </AppProvider></AuthProvider>,
    );
    expect(auth.localDevelopmentMode).toBe(true);
    await waitFor(() => expect(screen.getByTestId("current-path")).toHaveTextContent("/app"));
    expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument();
  });

  it("opens accessible mobile navigation and links to existing workspace routes", async () => {
    render(
      <AuthProvider><AppProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </AppProvider></AuthProvider>,
    );

    const menuButton = screen.getByRole("button", { name: "Open navigation" });
    fireEvent.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    const mobileNav = screen.getByRole("navigation", { name: "Mobile navigation" });
    expect(mobileNav).toBeInTheDocument();
    expect(within(mobileNav).getByRole("link", { name: /explore workspace/i })).toHaveAttribute("href", "/app");
    expect(within(mobileNav).getByRole("link", { name: /^capabilities/i })).toHaveAttribute("href", "#capabilities");
    expect(screen.getAllByRole("link", { name: /data validation/i }).some((link) => link.getAttribute("href") === "/app/data")).toBe(true);
    expect(screen.getByRole("link", { name: /backtesting & evaluation/i })).toHaveAttribute("href", "/app/backtest");
  });

  it("opens protected workspace routes in loopback development mode", async () => {
    render(
      <AuthProvider><AppProvider>
        <MemoryRouter initialEntries={["/app/plan"]}>
          <App />
          <CurrentPath />
        </MemoryRouter>
      </AppProvider></AuthProvider>,
    );
    expect(await screen.findByTestId("current-path")).toHaveTextContent("/app/plan");
  });
});
