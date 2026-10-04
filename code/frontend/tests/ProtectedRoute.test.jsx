// @vitest-environment jsdom
//
// The route guards (WS3, Iteration 1): ProtectedRoute keeps signed-out visitors off the
// deck pages, and GuestOnlyRoute keeps signed-in users off the login form. useAuth is
// replaced with a plain object, so each test sets the session it needs.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import ProtectedRoute, { GuestOnlyRoute } from '../src/auth/ProtectedRoute.jsx';

const auth = vi.hoisted(() => ({ user: null, loading: false }));
vi.mock('../src/auth/AuthContext.jsx', () => ({ useAuth: () => auth }));

afterEach(() => {
  cleanup();
  Object.assign(auth, { user: null, loading: false });
});

/** Shows where the redirect said the visitor was going. */
function LoginPage() {
  const location = useLocation();
  return <p>Login page, from {location.state?.from?.pathname ?? 'nowhere'}</p>;
}

function renderAt(path) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<GuestOnlyRoute><LoginPage /></GuestOnlyRoute>} />
        <Route path="/decks" element={<ProtectedRoute><p>Deck list</p></ProtectedRoute>} />
        <Route path="/decks/:id" element={<ProtectedRoute><p>One deck</p></ProtectedRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

test('while /me is still answering, a protected page waits instead of redirecting', () => {
  auth.loading = true;
  renderAt('/decks/2');

  expect(screen.getByText('Loading…')).toBeTruthy();
  expect(screen.queryByText(/Login page/)).toBeNull();
});

test('signed out, a protected page sends you to login and remembers where you were going', () => {
  renderAt('/decks/2');

  expect(screen.getByText('Login page, from /decks/2')).toBeTruthy();
  expect(screen.queryByText('One deck')).toBeNull();
});

test('signed in, a protected page shows', () => {
  auth.user = { id: 1, email: 'demo@cadence.local' };
  renderAt('/decks/2');

  expect(screen.getByText('One deck')).toBeTruthy();
});

test('signed in, the login page sends you to your decks', () => {
  auth.user = { id: 1, email: 'demo@cadence.local' };
  renderAt('/login');

  expect(screen.getByText('Deck list')).toBeTruthy();
});

test('signed out, the login page shows', () => {
  renderAt('/login');

  expect(screen.getByText('Login page, from nowhere')).toBeTruthy();
});

test('while /me is still answering, the login page waits too', () => {
  auth.loading = true;
  renderAt('/login');

  expect(screen.getByText('Loading…')).toBeTruthy();
});
