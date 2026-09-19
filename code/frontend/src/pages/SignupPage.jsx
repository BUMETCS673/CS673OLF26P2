/**
 * Create an account — WS3 (Duc).
 *
 * Registering signs you in as well (the backend sets the session cookie on the 201),
 * so this goes straight to the deck list rather than bouncing through the login form.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import {
  MAX_DISPLAY_NAME_LENGTH,
  MAX_EMAIL_LENGTH,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  validateDisplayName,
  validateEmail,
  validatePassword,
} from "../auth/validation";

export default function SignupPage() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();

    const errors = {};
    const emailError = validateEmail(email);
    const passwordError = validatePassword(password);
    const displayNameError = validateDisplayName(displayName);
    if (emailError) errors.email = emailError;
    if (passwordError) errors.password = passwordError;
    if (displayNameError) errors.display_name = displayNameError;

    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      await register({ email: email.trim(), password, displayName });
      navigate("/decks", { replace: true });
    } catch (err) {
      if (err.code === "conflict") {
        // The email is taken -- that belongs next to the email field, not in a banner.
        setFieldErrors({ email: err.message });
      } else if (err.code === "validation_error" && err.field) {
        setFieldErrors({ [err.field]: err.message });
      } else {
        setFormError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <h1>Create your account</h1>

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
          maxLength={MAX_EMAIL_LENGTH}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={Boolean(fieldErrors.email)}
          disabled={submitting}
        />
        {fieldErrors.email && <p className="field-error">{fieldErrors.email}</p>}

        <label htmlFor="display_name">
          Display name <span className="optional">(optional)</span>
        </label>
        <input
          id="display_name"
          name="display_name"
          type="text"
          autoComplete="nickname"
          maxLength={MAX_DISPLAY_NAME_LENGTH}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          aria-invalid={Boolean(fieldErrors.display_name)}
          disabled={submitting}
        />
        {fieldErrors.display_name && <p className="field-error">{fieldErrors.display_name}</p>}

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          maxLength={MAX_PASSWORD_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={Boolean(fieldErrors.password)}
          disabled={submitting}
        />
        {fieldErrors.password ? (
          <p className="field-error">{fieldErrors.password}</p>
        ) : (
          <p className="field-hint">At least {MIN_PASSWORD_LENGTH} characters.</p>
        )}

        <button type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
