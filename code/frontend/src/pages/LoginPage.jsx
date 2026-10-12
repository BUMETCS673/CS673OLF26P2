/**
 * Sign in — WS3 (Duc).
 *
 * Only checks that the fields are filled in. The 8-character rule isn't run here on
 * purpose: the backend doesn't run it on login either, so a short guess comes back as
 * simply wrong rather than as the wrong shape. Every login failure looks the same.
 */

/*
 * Step 0c: the wordmark, and the design system's class names on the error message
 * and the Sign in button.
 * AI Utilization: ~100% of those edits
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Restyling onto the shared design system
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/*
 * Iteration 3 refactor: the submit flow and fields through useAuthForm() and AuthField.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import AuthField from "../auth/AuthField";
import { useAuthForm } from "../auth/useAuthForm";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Where they were headed before ProtectedRoute sent them here, if anywhere.
  const destination = location.state?.from?.pathname ?? "/decks";

  // A 401, the usual failure, goes in the banner and says nothing about which half of
  // the pair was wrong -- that's deliberate on the backend, so don't dress it up.
  const { fieldErrors, formError, submitting, handleSubmit } = useAuthForm({
    validate() {
      const errors = {};
      if (!email.trim()) errors.email = "Email is required.";
      if (!password) errors.password = "Password is required.";
      return errors;
    },
    async submit() {
      await login({ email: email.trim(), password });
      navigate(destination, { replace: true });
    },
  });

  return (
    <main className="auth-page">
      <p className="wordmark">Cadence</p>
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <h1>Sign in to Cadence</h1>

        {formError && (
          <p className="error-message" role="alert">
            {formError}
          </p>
        )}

        <AuthField
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          disabled={submitting}
        />

        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          disabled={submitting}
        />

        <button className="button primary" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>

        <p className="auth-switch">
          New here? <Link to="/signup">Create an account</Link>
        </p>
      </form>
    </main>
  );
}
