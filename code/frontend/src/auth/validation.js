/**
 * The contract's validation rules, on the frontend — WS3 (Duc).
 *
 * These mirror `backend/app/api/auth.py` exactly, and they exist so the user gets a
 * fast, friendly message instead of a round trip. They are *not* the defense: the
 * backend checks the same things, because the frontend can be bypassed.
 *
 * Each function returns a message string, or null when the value is fine.
 */

export const MAX_EMAIL_LENGTH = 255;
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;
export const MAX_DISPLAY_NAME_LENGTH = 120;

// Same deliberately loose shape the backend uses: rules out what obviously isn't an
// address, and leaves the real proof to sending mail, which we don't do.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function validateEmail(value) {
  const email = value.trim();
  if (!email) return "Email is required.";
  if (email.length > MAX_EMAIL_LENGTH) return `Email must be ${MAX_EMAIL_LENGTH} characters or fewer.`;
  if (!EMAIL_PATTERN.test(email)) return "Email must look like name@example.com.";
  return null;
}

/**
 * Signup only. The login form deliberately doesn't run this: the backend doesn't either,
 * so that a short guess fails as simply wrong rather than as the wrong *shape*.
 */
export function validatePassword(value) {
  if (!value) return "Password is required.";
  if (value.length < MIN_PASSWORD_LENGTH) return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (value.length > MAX_PASSWORD_LENGTH) return `Password must be ${MAX_PASSWORD_LENGTH} characters or fewer.`;
  if (!value.trim()) return "Password can't be only spaces.";
  return null;
}

/** Optional field, so blank is fine. The cap is the column width in the users table. */
export function validateDisplayName(value) {
  const name = value.trim();
  if (name.length > MAX_DISPLAY_NAME_LENGTH) {
    return `Display name must be ${MAX_DISPLAY_NAME_LENGTH} characters or fewer.`;
  }
  return null;
}
