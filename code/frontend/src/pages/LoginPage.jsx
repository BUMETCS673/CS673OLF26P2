/**
 * Sign in — WS3 (Duc).
 *
 * Only checks that the fields are filled in. The 8-character rule isn't run here on
 * purpose: the backend doesn't run it on login either, so a short guess comes back as
 * simply wrong rather than as the wrong shape. Every login failure looks the same.
 */

import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Where they were headed before ProtectedRoute sent them here, if anywhere.
  const destination = location.state?.from?.pathname ?? "/decks";

  async function handleSubmit(event) {
    event.preventDefault();

    const errors = {};
    if (!email.trim()) errors.email = "Email is required.";
    if (!password) errors.password = "Password is required.";

    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      await login({ email: email.trim(), password });
      navigate(destination, { replace: true });
    } catch (err) {
      if (err.code === "validation_error" && err.field) {
        setFieldErrors({ [err.field]: err.message });
      } else {
        // Covers the 401, which is the usual one and says nothing about which half of
        // the pair was wrong -- that's deliberate on the backend, so don't dress it up.
        setFormError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <h1>Sign in to Cadence</h1>

        {formError && (
          <p className="form-error" role="alert">
            {formError}
          </p>
        )}

        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={Boolean(fieldErrors.email)}
          disabled={submitting}
        />
        {fieldErrors.email && <p className="field-error">{fieldErrors.email}</p>}

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={Boolean(fieldErrors.password)}
          disabled={submitting}
        />
        {fieldErrors.password && <p className="field-error">{fieldErrors.password}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>

        <p className="auth-switch">
          New here? <Link to="/signup">Create an account</Link>
        </p>
      </form>
    </main>
  );
}
