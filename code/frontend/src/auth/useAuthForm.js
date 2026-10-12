/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useState } from "react";

/**
 * The submit flow the sign-in and sign-up forms share: check the fields, send, and put a
 * failure next to its field or in the banner.
 *
 * validate     () => { [field]: message }, empty when the form can be sent
 * submit       () => Promise, the request plus whatever happens after it succeeds
 * errorFields  { [error code]: field } for errors that belong next to a field even
 *              without err.field, e.g. { conflict: "email" } for a taken email
 */
export function useAuthForm({ validate, submit, errorFields = {} }) {
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();

    const errors = validate();
    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      await submit();
    } catch (err) {
      const field = errorFields[err.code] ?? (err.code === "validation_error" ? err.field : null);
      if (field) {
        setFieldErrors({ [field]: err.message });
      } else {
        setFormError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return { fieldErrors, formError, submitting, handleSubmit };
}
