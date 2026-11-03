import { Activity, BrainCircuit, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { BrandLogo } from "../components/Brand";
import { Spinner } from "../components/ui";

const DEMO = [
  { email: "admin@northwind.demo", label: "Northwind · Admin" },
  { email: "analyst@northwind.demo", label: "Northwind · Analyst" },
  { email: "viewer@northwind.demo", label: "Northwind · Viewer" },
  { email: "analyst@meridian.demo", label: "Meridian · Analyst" },
];

const CAPABILITIES = [
  { icon: Activity, title: "Real-time scoring", text: "Kafka events validated, deduplicated and scored in milliseconds." },
  { icon: BrainCircuit, title: "Explainable risk", text: "Every score ships with counterfactual feature contributions." },
  { icon: Search, title: "Grounded investigations", text: "LangGraph case reports that cite database evidence, never invent it." },
];

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("admin@northwind.demo");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full bg-surface lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-6 py-8 sm:px-12 lg:px-16">
        <div className="flex items-center gap-3">
          <BrandLogo height={38} />
          <div className="text-[17px] font-bold tracking-tight">AEGIS <span className="text-signal">AI</span></div>
        </div>

        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-12 animate-fadein">
          <h2 className="text-[30px] font-bold tracking-tight text-fg">Welcome back</h2>
          <p className="mt-2 text-[14px] text-fg-3">Sign in to the fraud intelligence workspace for your institution.</p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            <div>
              <label htmlFor="email" className="text-[13px] font-semibold text-fg">Email</label>
              <input id="email" className="input mt-1.5 py-2.5 text-[14px]" type="email" autoComplete="username" value={email}
                onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <label htmlFor="password" className="text-[13px] font-semibold text-fg">Password</label>
              <input id="password" className="input mt-1.5 py-2.5 text-[14px]" type="password" autoComplete="current-password" value={password}
                placeholder="••••••••" onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <div className="rounded-lg border border-[#fecaca] bg-[#fef2f2] px-3 py-2 text-[12.5px] font-medium text-[#b91c1c]" role="alert">{error}</div>}
            <button type="submit" className="btn-primary w-full py-2.5 text-[14px]" disabled={busy}>
              {busy && <Spinner />}Sign in
            </button>
          </form>

          <div className="mt-8 rounded-xl border border-line bg-sunken p-4">
            <div className="eyebrow mb-2.5">Demo accounts · local, non-production</div>
            <div className="grid grid-cols-2 gap-2">
              {DEMO.map((d) => (
                <button type="button" key={d.email} onClick={() => setEmail(d.email)}
                  className={`rounded-lg border px-2.5 py-2 text-left text-[12px] font-medium transition ${email === d.email
                    ? "border-signal bg-signal-soft text-signal" : "border-line bg-surface text-fg-2 hover:border-signal-ring hover:text-signal"}`}>
                  {d.label}
                </button>
              ))}
            </div>
            <p className="mt-3 text-[11.5px] text-fg-3">Password is <span className="num font-medium text-fg-2">AEGIS_DEMO_USER_PASSWORD</span> from your local <span className="num">.env</span>.</p>
          </div>
        </div>
        <p className="text-[11.5px] text-fg-4">Synthetic data only. Research & review platform — no automated financial decisions.</p>
      </div>

      <div className="relative hidden overflow-hidden bg-gradient-to-br from-[#2563eb] via-[#1d4ed8] to-[#1e3a8a] lg:flex lg:flex-col lg:justify-center lg:px-16">
        <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-[#60a5fa]/25 blur-3xl" />
        <div className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:linear-gradient(#fff_1px,transparent_1px),linear-gradient(90deg,#fff_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="relative max-w-[520px] text-white">
          <span className="mb-8 inline-grid h-16 w-16 place-items-center rounded-2xl bg-white shadow-[0_12px_32px_-8px_rgba(15,23,42,0.45)]">
            <BrandLogo height={34} />
          </span>
          <br />
          <span className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-[12px] font-medium ring-1 ring-white/25">
            <span className="h-1.5 w-1.5 rounded-full bg-[#4ade80]" />Real-time financial intelligence
          </span>
          <h3 className="mt-6 text-[34px] font-bold leading-tight tracking-tight">Detect fraud as it happens.<br />Explain every decision.</h3>
          <p className="mt-4 text-[15px] leading-relaxed text-white/80">
            Streaming risk scoring, data-quality controls and evidence-grounded investigations in one workspace.
          </p>
          <ul className="mt-10 space-y-4">
            {CAPABILITIES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4 rounded-2xl bg-white/10 p-4 ring-1 ring-white/15 backdrop-blur-sm">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-signal"><Icon className="h-5 w-5" /></span>
                <div>
                  <div className="text-[14px] font-semibold">{title}</div>
                  <div className="mt-0.5 text-[13px] text-white/75">{text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
