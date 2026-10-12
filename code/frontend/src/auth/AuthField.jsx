/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

/**
 * One labelled input on the sign-in or sign-up form, with its error, or its hint when
 * there's no error. `id` is also the input's name. Other props go to the <input>.
 */
export default function AuthField({ id, label, error, hint, ...inputProps }) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input id={id} name={id} aria-invalid={Boolean(error)} {...inputProps} />
      {error ? (
        <p className="field-error">{error}</p>
      ) : (
        hint && <p className="field-hint">{hint}</p>
      )}
    </>
  );
}
