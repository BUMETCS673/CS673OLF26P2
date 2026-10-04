// @vitest-environment jsdom
//
// The create-account page (WS3, Iteration 1). useAuth is replaced with a plain object
// holding a mock register(), so these tests never touch fetch. The rules themselves are
// covered in validation.test.mjs; here it's how the page uses them.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import SignupPage from '../src/pages/SignupPage.jsx';

const auth = vi.hoisted(() => ({ register: null }));
vi.mock('../src/auth/AuthContext.jsx', () => ({ useAuth: () => auth }));

afterEach(cleanup);

const apiError = (code, message, field) => Object.assign(new Error(message), { code, field });

function renderSignup(register = vi.fn().mockResolvedValue({ id: 1 })) {
  auth.register = register;
  render(
    <MemoryRouter initialEntries={['/signup']}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<p>Login page</p>} />
        <Route path="/decks" element={<p>Deck list</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return register;
}

const email = () => screen.getByLabelText('Email');
const displayName = () => screen.getByLabelText(/Display name/);
const password = () => screen.getByLabelText('Password');
const type = (input, value) => fireEvent.change(input, { target: { value } });
const createAccount = () => fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

function fillIn() {
  type(email(), 'new@cadence.local');
  type(displayName(), 'New Learner');
  type(password(), 'longenough');
}

test('the password hint shows until there is a password error', () => {
  renderSignup();

  expect(screen.getByText('At least 8 characters.')).toBeTruthy();
});

test("the email and password rules run before anything is sent", () => {
  const register = renderSignup();

  type(email(), 'not-an-email');
  type(password(), 'short');
  createAccount();

  expect(screen.getByText('Email must look like name@example.com.')).toBeTruthy();
  expect(screen.getByText('Password must be at least 8 characters.')).toBeTruthy();
  expect(screen.queryByText('At least 8 characters.')).toBeNull();
  expect(password().getAttribute('aria-invalid')).toBe('true');
  expect(register).not.toHaveBeenCalled();
});

test('a display name over 120 characters is too long', () => {
  const register = renderSignup();

  fillIn();
  type(displayName(), 'a'.repeat(121));
  createAccount();

  expect(screen.getByText('Display name must be 120 characters or fewer.')).toBeTruthy();
  expect(register).not.toHaveBeenCalled();
});

test('a valid form registers with the trimmed email and goes to the deck list', async () => {
  const register = renderSignup();

  fillIn();
  type(email(), '  new@cadence.local ');
  createAccount();

  expect(register).toHaveBeenCalledWith({
    email: 'new@cadence.local',
    password: 'longenough',
    displayName: 'New Learner',
  });
  expect(await screen.findByText('Deck list')).toBeTruthy();
});

test('while creating the account, the form is disabled and says so', () => {
  renderSignup(vi.fn(() => new Promise(() => {})));

  fillIn();
  createAccount();

  expect(screen.getByRole('button', { name: 'Creating account…' }).disabled).toBe(true);
  expect(email().disabled).toBe(true);
});

test('an email that is already taken is reported next to the email field', async () => {
  renderSignup(vi.fn().mockRejectedValue(apiError('conflict', 'That email is already registered.')));

  fillIn();
  createAccount();

  expect(await screen.findByText('That email is already registered.')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
  expect(email().getAttribute('aria-invalid')).toBe('true');
});

test("the server's validation error for a field shows next to that field", async () => {
  renderSignup(vi.fn().mockRejectedValue(
    apiError('validation_error', 'Display name is too long.', 'display_name'),
  ));

  fillIn();
  createAccount();

  expect(await screen.findByText('Display name is too long.')).toBeTruthy();
  expect(displayName().getAttribute('aria-invalid')).toBe('true');
});

test('any other failure shows as a banner', async () => {
  renderSignup(vi.fn().mockRejectedValue(apiError('network_error', "Can't reach the server.")));

  fillIn();
  createAccount();

  expect((await screen.findByRole('alert')).textContent).toBe("Can't reach the server.");
});

test('Sign in links to the login page', () => {
  renderSignup();

  fireEvent.click(screen.getByRole('link', { name: 'Sign in' }));

  expect(screen.getByText('Login page')).toBeTruthy();
});
