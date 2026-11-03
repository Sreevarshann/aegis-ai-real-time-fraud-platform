import clsx from "clsx";
import { Activity, BrainCircuit, Database, LayoutDashboard, LogOut, Menu, Search, ServerCog, ShieldCheck, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { StatusDot } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/transactions", label: "Live Transactions", icon: Activity },
  { to: "/investigations", label: "Fraud Investigations", icon: Search },
  { to: "/data", label: "Data Intelligence", icon: Database },
  { to: "/models", label: "Model Intelligence", icon: BrainCircuit },
  { to: "/operations", label: "System Operations", icon: ServerCog },
];

interface Health { services: Record<string, { status: string }> }

function HealthIndicator() {
  const { data, isError } = useQuery({
    queryKey: ["health"], queryFn: () => api<Health>("/operations/health"), refetchInterval: 15_000,
  });
  const services = data ? Object.values(data.services) : [];
  const down = services.filter((s) => s.status === "down").length;
  const status = isError ? "down" : !data ? "unknown" : down ? "warn" : "up";
  return (
    <NavLink to="/operations" className="flex items-center gap-2 rounded-lg border border-line bg-ink-850 px-3 py-1.5 text-[12px] text-mist-300 hover:text-mist-100">
      <StatusDot status={status} />
      {status === "up" ? "All systems operational" : status === "warn" ? `${down} service(s) degraded` : status === "down" ? "API unreachable" : "Checking…"}
    </NavLink>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const current = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-3">
      {NAV.map(({ to, label, icon: Icon }) => (
        <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
          className={({ isActive }) => clsx(
            "group flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition",
            isActive ? "bg-signal/10 text-mist-100 shadow-[inset_2px_0_0_#4c8dff]" : "text-mist-400 hover:bg-ink-800 hover:text-mist-100",
          )}>
          <Icon className="h-4 w-4 shrink-0" />{label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <aside className={clsx(
        "fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-line bg-ink-900/95 backdrop-blur transition-transform",
        "lg:static lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}>
       <div className="flex h-full flex-col lg:sticky lg:top-0 lg:h-screen">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-signal/30 to-teal/20 ring-1 ring-signal/40">
            <ShieldCheck className="h-4.5 w-4.5 text-signal" />
          </div>
          <div>
            <div className="text-[14px] font-semibold tracking-wide">AEGIS<span className="text-signal"> AI</span></div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-mist-500">Financial Intelligence</div>
          </div>
          <button className="ml-auto lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
        </div>
        {nav}
        <div className="m-3 rounded-lg border border-line bg-ink-850 p-3">
          <div className="truncate text-[13px] font-medium">{user?.full_name}</div>
          <div className="truncate text-[11px] text-mist-500">{user?.email}</div>
          <div className="mt-2 flex items-center justify-between">
            <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-mist-300">{user?.role} · {user?.tenant_id}</span>
            <button onClick={logout} className="text-mist-500 hover:text-mist-100" aria-label="Sign out" title="Sign out"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
        <p className="px-5 pb-4 text-[10px] leading-relaxed text-mist-500">Synthetic data only. Research & review platform — no automated financial decisions.</p>
       </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-ink-950/80 px-4 py-3 backdrop-blur md:px-8">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <div>
            <div className="eyebrow">{user?.tenant_id === "northwind" ? "Northwind Bank" : "Meridian Credit Union"} · synthetic tenant</div>
            <h1 className="text-[17px] font-semibold tracking-tight">{current?.label ?? "Investigation"}</h1>
          </div>
          <div className="ml-auto hidden sm:block"><HealthIndicator /></div>
        </header>
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
