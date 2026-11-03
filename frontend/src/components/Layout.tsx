import clsx from "clsx";
import {
  Activity, BookOpen, BrainCircuit, Building2, ChevronRight, Database, LayoutDashboard, LogOut, Menu, Search, ServerCog,
  X,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { BrandLogo } from "./Brand";
import { StatusDot } from "./ui";

const SECTIONS = [
  {
    label: "Monitoring",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard },
      { to: "/transactions", label: "Live Transactions", icon: Activity },
      { to: "/investigations", label: "Fraud Investigations", icon: Search },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/data", label: "Data Intelligence", icon: Database },
      { to: "/models", label: "Model Intelligence", icon: BrainCircuit },
    ],
  },
  { label: "Platform", items: [{ to: "/operations", label: "System Operations", icon: ServerCog }] },
];
const NAV = SECTIONS.flatMap((s) => s.items);
const TENANT_NAME: Record<string, string> = { northwind: "Northwind Bank", meridian: "Meridian Credit Union" };
const DOCS_URL = "https://github.com/Sreevarshann/aegis-ai-real-time-fraud-platform/tree/main/docs";

interface Health { services: Record<string, { status: string }> }

function HealthChip() {
  const { data, isError } = useQuery({
    queryKey: ["health"], queryFn: () => api<Health>("/operations/health"), refetchInterval: 15_000,
  });
  const services = data ? Object.values(data.services) : [];
  const down = services.filter((s) => s.status === "down").length;
  const status = isError ? "down" : !data ? "unknown" : down ? "warn" : "up";
  return (
    <NavLink to="/operations" className={clsx(
      "flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] font-medium transition hover:shadow-sm",
      status === "up" ? "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]" : status === "unknown" ? "border-line bg-sunken text-fg-3"
        : "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",
    )}>
      <StatusDot status={status} />
      {status === "up" ? "All systems operational" : status === "warn" ? `${down} service(s) degraded` : status === "down" ? "API unreachable" : "Checking…"}
    </NavLink>
  );
}

function GlobalSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length >= 2) navigate(`/transactions?q=${encodeURIComponent(q.trim())}`);
  };
  return (
    <form onSubmit={submit} className="relative hidden md:block" role="search">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-4" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customer, merchant, device…"
        aria-label="Search transactions" className="input w-72 rounded-full pl-9" />
    </form>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const current = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));
  const tenant = TENANT_NAME[user?.tenant_id ?? ""] ?? user?.tenant_id ?? "";
  const initials = (user?.full_name ?? "?").split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  const title = current?.label ?? "Investigation";

  return (
    <div className="flex min-h-full">
      <aside className={clsx(
        "fixed inset-y-0 left-0 z-40 w-64 shrink-0 border-r border-line bg-surface transition-transform",
        "lg:static lg:translate-x-0",
        open ? "translate-x-0 shadow-lift" : "-translate-x-full",
      )}>
        <div className="flex h-full flex-col lg:sticky lg:top-0 lg:h-screen">
          <div className="flex items-center gap-3 px-6 py-6">
            <BrandLogo height={34} />
            <div>
              <div className="text-[16px] font-bold tracking-tight text-fg">AEGIS <span className="text-signal">AI</span></div>
              <div className="text-[10.5px] font-medium uppercase tracking-[0.14em] text-fg-3">Fraud Intelligence</div>
            </div>
            <button className="ml-auto text-fg-3 lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
          </div>
          <div className="mx-6 h-px bg-line" />

          <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-4 py-5">
            {SECTIONS.map((section) => (
              <div key={section.label}>
                <div className="eyebrow mb-2 px-3">{section.label}</div>
                <div className="flex flex-col gap-1">
                  {section.items.map(({ to, label, icon: Icon }) => (
                    <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
                      className={({ isActive }) => clsx(
                        "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-medium transition",
                        isActive ? "bg-signal-soft text-signal" : "text-fg-2 hover:bg-hover hover:text-fg",
                      )}>
                      {({ isActive }) => (
                        <>
                          <span className={clsx("grid h-8 w-8 place-items-center rounded-lg transition",
                            isActive ? "bg-signal text-white shadow-brand" : "bg-sunken text-fg-3 ring-1 ring-line group-hover:text-signal")}>
                            <Icon className="h-4 w-4" />
                          </span>
                          {label}
                        </>
                      )}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div className="m-4 overflow-hidden rounded-2xl bg-gradient-to-br from-[#3b82f6] to-[#1e40af] p-5 text-white shadow-brand">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-white/15"><BookOpen className="h-4 w-4" /></span>
            <div className="mt-3 text-[14px] font-semibold">Need the details?</div>
            <p className="mt-1 text-[12px] leading-relaxed text-white/80">Architecture, pipeline guarantees and model methodology.</p>
            <a href={DOCS_URL} target="_blank" rel="noreferrer"
              className="mt-3 inline-flex w-full items-center justify-center rounded-lg bg-white px-3 py-2 text-[12px] font-semibold text-signal hover:bg-white/90">
              Read the docs
            </a>
          </div>
          <p className="px-6 pb-5 text-[10.5px] leading-relaxed text-fg-3">Synthetic data only · research & review platform — no automated financial decisions.</p>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-fg/30 backdrop-blur-[1px] lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
          <div className="mx-auto flex w-full max-w-[1520px] items-center gap-3 px-4 py-3.5 md:px-8">
            <button className="text-fg-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
            <div className="min-w-0">
              <div className="flex items-center gap-1 text-[12px] text-fg-3">
                <span>AEGIS</span><ChevronRight className="h-3 w-3" /><span className="truncate">{title}</span>
              </div>
              <h1 className="truncate text-[18px] font-semibold tracking-tight text-fg">{title}</h1>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <GlobalSearch />
              <span className="hidden items-center gap-1.5 rounded-full border border-line bg-sunken px-3 py-1.5 text-[12px] font-medium text-fg-2 xl:inline-flex"
                title="Tenant from your session">
                <Building2 className="h-3.5 w-3.5 text-signal" />
                <span>{tenant} · synthetic tenant</span>
              </span>
              <span className="hidden sm:block"><HealthChip /></span>
              <div className="flex items-center gap-2.5 border-l border-line pl-3">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-signal-soft text-[12px] font-bold text-signal ring-1 ring-signal-ring">{initials}</span>
                <div className="hidden leading-tight md:block">
                  <div className="text-[13px] font-semibold text-fg">{user?.full_name}</div>
                  <div className="text-[11px] capitalize text-fg-3">{user?.role}</div>
                </div>
                <button onClick={logout} className="grid h-8 w-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-signal"
                  aria-label="Sign out" title="Sign out"><LogOut className="h-4 w-4" /></button>
              </div>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1520px] flex-1 px-4 py-7 md:px-8">{children}</main>
      </div>
    </div>
  );
}
