// @vitest-environment jsdom
//
// The signed-in header (WS3, Iteration 1). useAuth is replaced with a plain object, so
// each test sets the session it needs.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Header from '../src/components/Header.jsx';

const auth = vi.hoisted(() => ({ user: null, logout: null }));
vi.mock('../src/auth/AuthContext.jsx', () => ({ useAuth: () => auth }));

afterEach(() => {
  cleanup();
  Object.assign(auth, { user: null, logout: vi.fn() });
});

function renderHeader() {
  return render(
    <MemoryRouter initialEntries={['/decks']}>
      <Header />
      <Routes>
        <Route path="/decks" element={<p>Deck list</p>} />
        <Route path="/login" element={<p>Login page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

test('signed out, there is no header at all', () => {
  renderHeader();

  expect(screen.queryByRole('banner')).toBeNull();
});

test("signed in, it shows the wordmark linking to the decks, and the user's display name", () => {
  auth.user = { id: 1, email: 'demo@cadence.local', display_name: 'Demo User' };
  renderHeader();

  expect(screen.getByRole('link', { name: 'Cadence' }).getAttribute('href')).toBe('/decks');
  expect(screen.getByText('Demo User')).toBeTruthy();
});

test('without a display name, it falls back to the email', () => {
  auth.user = { id: 1, email: 'demo@cadence.local', display_name: null };
  renderHeader();

  expect(screen.getByText('demo@cadence.local')).toBeTruthy();
});

test('Sign out shows progress, logs out, and goes to the login page', async () => {
  let finish;
  auth.user = { id: 1, email: 'demo@cadence.local' };
  auth.logout = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
  renderHeader();

  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

  const button = screen.getByRole('button', { name: 'Signing out…' });
  expect(button.disabled).toBe(true);
  expect(auth.logout).toHaveBeenCalledTimes(1);

  finish();
  expect(await screen.findByText('Login page')).toBeTruthy();
});
