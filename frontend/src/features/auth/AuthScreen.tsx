import { Eye, EyeOff, Landmark, LockKeyhole, ShieldCheck, User } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";

import { login, register } from "../../api";
import { InlineAlert } from "../../components/InlineAlert";
import { errorMessage } from "../../lib/errors";
import type { AuthSession } from "../../types";

type AuthMode = "login" | "register";

export function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (session: AuthSession) => void;
}) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitLabel = mode === "login" ? "Sign in" : "Create account";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Email is required.");
      return;
    }
    if (mode === "register" && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (mode === "login" && !password) {
      setError("Password is required.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response =
        mode === "login"
          ? await login(email.trim(), password)
          : await register(email.trim(), password);
      onAuthenticated({
        accessToken: response.access_token,
        workspaceId: response.workspace_id,
        email: email.trim().toLowerCase(),
        isAdmin: response.is_admin,
      });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand-mark" aria-hidden="true">
          <div className="brand-mark">K</div>
        </div>
        <h1 id="auth-title">Kintiga Evidence Assistant</h1>
        <p className="auth-subtitle">Secure market-access evidence workbench</p>

        <div className="segmented-control" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={mode === "login" ? "active" : ""}
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Login
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            className={mode === "register" ? "active" : ""}
            onClick={() => {
              setMode("register");
              setError(null);
            }}
          >
            Register
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            Email
            <span className="input-with-icon">
              <User size={18} aria-hidden="true" />
              <input
                autoComplete="email"
                inputMode="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="analyst@example.com"
              />
            </span>
          </label>
          <label>
            Password
            <span className="input-with-icon password-field">
              <LockKeyhole size={18} aria-hidden="true" />
              <input
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={mode === "login" ? "Your password" : "At least 8 characters"}
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((current) => !current)}
              >
                {showPassword ? (
                  <EyeOff size={18} aria-hidden="true" />
                ) : (
                  <Eye size={18} aria-hidden="true" />
                )}
              </button>
            </span>
          </label>
          {mode === "login" ? (
            <button
              className="link-button forgot-password"
              type="button"
              onClick={() => setError("Password reset is not available in this demo.")}
            >
              Forgot password?
            </button>
          ) : null}
          {error ? <InlineAlert tone="error" message={error} /> : null}
          <button className="primary-button full-width" type="submit" disabled={isSubmitting}>
            <ShieldCheck size={18} aria-hidden="true" />
            {isSubmitting ? "Working..." : submitLabel}
          </button>
          <div className="auth-divider">
            <span>or</span>
          </div>
          <button className="icon-text-button full-width sso-button" type="button" disabled>
            <Landmark size={18} aria-hidden="true" />
            Continue with SSO
          </button>
          <p className="auth-security-note">
            <ShieldCheck size={18} aria-hidden="true" />
            Your data is encrypted and securely protected
          </p>
        </form>
      </section>
    </main>
  );
}
