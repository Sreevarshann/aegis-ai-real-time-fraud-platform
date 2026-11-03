import { ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/ui";

const DEMO = [
  { email: "admin@northwind.demo", label: "Northwind · Admin" },
  { email: "analyst@northwind.demo", label: "Northwind · Analyst" },
  { email: "viewer@northwind.demo", label: "Northwind · Viewer" },
  { email: "analyst@meridian.demo", label: "Meridian · Analyst" },
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
    <div className="grid min-h-full place-items-center px-4 py-12">
      <div className="w-full max-w-[400px] animate-fadein">
        <div className="mb-8 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-signal/30 to-teal/20 ring-1 ring-signal/40">
            <ShieldCheck className="h-5 w-5 text-signal" />
          </div>
          <div>
            <div className="text-[18px] font-semibold tracking-wide">AEGIS<span className="text-signal"> AI</span></div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-mist-500">Real-time financial intelligence</div>
          </div>
        </div>
        <form onSubmit={submit} className="panel space-y-4 p-6">
          <div>
            <label htmlFor="email" className="eyebrow">Email</label>
            <input id="email" className="input mt-1.5" type="email" autoComplete="username" value={email}
              onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="password" className="eyebrow">Password</label>
            <input id="password" className="input mt-1.5" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div className="rounded-lg border border-risk-critical/30 bg-risk-critical/10 px-3 py-2 text-[12px] text-risk-critical" role="alert">{error}</div>}
          <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
            {busy && <Spinner />}Sign in
          </button>
          <div className="border-t border-line pt-4">
            <div className="eyebrow mb-2">Demo accounts (local, non-production)</div>
            <div className="grid grid-cols-2 gap-1.5">
              {DEMO.map((d) => (
                <button type="button" key={d.email} onClick={() => setEmail(d.email)}
                  className="rounded-md border border-line px-2 py-1.5 text-left text-[11px] text-mist-300 hover:border-signal/40 hover:text-mist-100">
                  {d.label}
                </button>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-mist-500">Password is <span className="num">AEGIS_DEMO_USER_PASSWORD</span> from your local <span className="num">.env</span>.</p>
          </div>
        </form>
      </div>
    </div>
  );
}
