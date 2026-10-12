/**
 * Create an account — WS3 (Duc).
 *
 * Registering signs you in as well (the backend sets the session cookie on the 201),
 * so this goes straight to the deck list rather than bouncing through the login form.
 */

/*
 * Step 0c: the wordmark, and the design system's class names on the error message
 * and the Create account button.
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
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import AuthField from "../auth/AuthField";
import { useAuthForm } from "../auth/useAuthForm";
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

  const { fieldErrors, formError, submitting, handleSubmit } = useAuthForm({
    validate() {
      const errors = {};
      const emailError = validateEmail(email);
      const passwordError = validatePassword(password);
      const displayNameError = validateDisplayName(displayName);
      if (emailError) errors.email = emailError;
      if (passwordError) errors.password = passwordError;
      if (displayNameError) errors.display_name = displayNameError;
      return errors;
    },
    async submit() {
      await register({ email: email.trim(), password, displayName });
      navigate("/decks", { replace: true });
    },
    // The email is taken -- that belongs next to the email field, not in a banner.
    errorFields: { conflict: "email" },
  });

  return (
    <main className="auth-page">
      <p className="wordmark">Cadence</p>
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <h1>Create your account</h1>

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
          maxLength={MAX_EMAIL_LENGTH}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          disabled={submitting}
        />

        <AuthField
          id="display_name"
          label={<>Display name <span className="optional">(optional)</span></>}
          type="text"
          autoComplete="nickname"
          maxLength={MAX_DISPLAY_NAME_LENGTH}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          error={fieldErrors.display_name}
          disabled={submitting}
        />

        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          maxLength={MAX_PASSWORD_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          disabled={submitting}
        />

        <button className="button primary" type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
