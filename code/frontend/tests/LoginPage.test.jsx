// @vitest-environment jsdom
//
// The sign-in page (WS3, Iteration 1). useAuth is replaced with a plain object holding a
// mock login(), so these tests never touch fetch.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import LoginPage from '../src/pages/LoginPage.jsx';

const auth = vi.hoisted(() => ({ login: null }));
vi.mock('../src/auth/AuthContext.jsx', () => ({ useAuth: () => auth }));

afterEach(cleanup);

const apiError = (code, message, field) => Object.assign(new Error(message), { code, field });

function renderLogin({ login = vi.fn().mockResolvedValue({ id: 1 }), from } = {}) {
  auth.login = login;
  render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: from ? { from: { pathname: from } } : null }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<p>Signup page</p>} />
        <Route path="/decks" element={<p>Deck list</p>} />
        <Route path="/decks/:id" element={<p>One deck</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return login;
}

const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const signIn = () => fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

function fillIn(email = 'demo@cadence.local', password = 'demo1234') {
  type('Email', email);
  type('Password', password);
}

test('both fields are required, and nothing is sent without them', () => {
  const login = renderLogin();

  signIn();

  expect(screen.getByText('Email is required.')).toBeTruthy();
  expect(screen.getByText('Password is required.')).toBeTruthy();
  expect(screen.getByLabelText('Email').getAttribute('aria-invalid')).toBe('true');
  expect(login).not.toHaveBeenCalled();
});

test("a short password is still sent: login doesn't check its length, on purpose", () => {
  const login = renderLogin();

  fillIn('demo@cadence.local', 'abc');
  signIn();

  expect(login).toHaveBeenCalledWith({ email: 'demo@cadence.local', password: 'abc' });
});

test('signing in sends the trimmed email and goes to the deck list', async () => {
  const login = renderLogin();

  fillIn('  demo@cadence.local ', 'demo1234');
  signIn();

  expect(login).toHaveBeenCalledWith({ email: 'demo@cadence.local', password: 'demo1234' });
  expect(await screen.findByText('Deck list')).toBeTruthy();
});

test('after being sent here from a deck, signing in goes back to that deck', async () => {
  renderLogin({ from: '/decks/2' });

  fillIn();
  signIn();

  expect(await screen.findByText('One deck')).toBeTruthy();
});

test('while signing in, the form is disabled and says so', () => {
  renderLogin({ login: vi.fn(() => new Promise(() => {})) });

  fillIn();
  signIn();

  expect(screen.getByRole('button', { name: 'Signing in…' }).disabled).toBe(true);
  expect(screen.getByLabelText('Email').disabled).toBe(true);
  expect(screen.getByLabelText('Password').disabled).toBe(true);
});

test("wrong credentials show the server's message and keep you on the page", async () => {
  renderLogin({ login: vi.fn().mockRejectedValue(apiError('unauthorized', 'Wrong email or password.')) });

  fillIn();
  signIn();

  expect((await screen.findByRole('alert')).textContent).toBe('Wrong email or password.');
  expect(screen.getByRole('button', { name: 'Sign in' }).disabled).toBe(false);
  expect(screen.getByLabelText('Email').value).toBe('demo@cadence.local');
});

test('a validation error for one field shows next to that field, not as a banner', async () => {
  renderLogin({ login: vi.fn().mockRejectedValue(apiError('validation_error', 'Email is too long.', 'email')) });

  fillIn();
  signIn();

  expect(await screen.findByText('Email is too long.')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

test('Create an account links to the signup page', () => {
  renderLogin();

  fireEvent.click(screen.getByRole('link', { name: 'Create an account' }));

  expect(screen.getByText('Signup page')).toBeTruthy();
});
