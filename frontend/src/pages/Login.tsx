import { useState, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { api } from "@/services/api";
import { SessionExpiredBanner } from "@/components/auth/SessionExpiredBanner";

interface LocationState {
  from?: { pathname?: string };
}

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.login(email, password);
      if (!res?.access) {
        throw new Error("Login response missing access token");
      }
      window.localStorage.setItem("nirogidhara.jwt", res.access);
      const state = location.state as LocationState | undefined;
      const next = state?.from?.pathname ?? "/saas-admin";
      navigate(next, { replace: true });
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message.replace(/^HTTP \d+\s*[—-]?\s*/, "")
          : "Invalid email or password",
      );
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-md space-y-6 rounded-lg border bg-card p-8 shadow-sm">
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Nirogidhara</h1>
          <p className="text-sm text-muted-foreground">Director Login</p>
        </header>
        {/* Phase 15K — Session Expired banner. Renders only when
            RequireAuth redirected the user here with a from-state. */}
        <SessionExpiredBanner />
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoFocus
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="director@example.com"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          {error && (
            <div
              role="alert"
              className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
