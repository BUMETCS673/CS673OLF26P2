// The signup and login forms' validation rules (WS3, Iteration 1). They mirror
// backend/app/api/auth.py, so these cases match the backend's.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { test } from 'vitest';
import assert from 'node:assert/strict';
import {
  MAX_DISPLAY_NAME_LENGTH,
  MAX_EMAIL_LENGTH,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  validateDisplayName,
  validateEmail,
  validatePassword,
} from '../src/auth/validation.js';

test('an email is required, and spaces alone count as blank', () => {
  assert.equal(validateEmail(''), 'Email is required.');
  assert.equal(validateEmail('   '), 'Email is required.');
});

test('an email has to look like name@example.com', () => {
  for (const email of ['demo', 'demo@', '@cadence.local', 'demo@cadence', 'de mo@cadence.local']) {
    assert.equal(validateEmail(email), 'Email must look like name@example.com.', email);
  }
});

test('an email over 255 characters is too long', () => {
  const email = `${'a'.repeat(MAX_EMAIL_LENGTH - '@b.co'.length + 1)}@b.co`;
  assert.equal(email.length, MAX_EMAIL_LENGTH + 1);
  assert.equal(validateEmail(email), 'Email must be 255 characters or fewer.');
});

test('a valid email passes, with spaces around it trimmed first', () => {
  assert.equal(validateEmail('demo@cadence.local'), null);
  assert.equal(validateEmail('  demo@cadence.local  '), null);
});

test('a password is required', () => {
  assert.equal(validatePassword(''), 'Password is required.');
});

test('a password needs 8 to 128 characters', () => {
  assert.equal(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH - 1)), 'Password must be at least 8 characters.');
  assert.equal(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH)), null);
  assert.equal(validatePassword('a'.repeat(MAX_PASSWORD_LENGTH)), null);
  assert.equal(validatePassword('a'.repeat(MAX_PASSWORD_LENGTH + 1)), 'Password must be 128 characters or fewer.');
});

test("a password of only spaces is rejected, even when it's long enough", () => {
  assert.equal(validatePassword(' '.repeat(MIN_PASSWORD_LENGTH)), "Password can't be only spaces.");
});

test('a display name is optional', () => {
  assert.equal(validateDisplayName(''), null);
  assert.equal(validateDisplayName('   '), null);
});

test('a display name can be 120 characters, trimmed, but not 121', () => {
  assert.equal(validateDisplayName('a'.repeat(MAX_DISPLAY_NAME_LENGTH)), null);
  assert.equal(validateDisplayName(` ${'a'.repeat(MAX_DISPLAY_NAME_LENGTH)} `), null);
  assert.equal(
    validateDisplayName('a'.repeat(MAX_DISPLAY_NAME_LENGTH + 1)),
    'Display name must be 120 characters or fewer.',
  );
});
