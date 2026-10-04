// @vitest-environment jsdom
//
// AuthProvider (WS3, Iteration 1): the session the whole app reads through useAuth().
// The auth API is replaced with mocks, so these tests never touch fetch.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { AuthProvider, useAuth } from '../src/auth/AuthContext.jsx';
import * as authApi from '../src/api/auth.js';

vi.mock('../src/api/auth.js', () => ({
  me: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.restoreAllMocks();
});

const DEMO = { id: 1, email: 'demo@cadence.local', display_name: 'Demo User' };
const apiError = (code, message = 'Something went wrong') => Object.assign(new Error(message), { code });

/** Renders the provider, and hands back the latest value useAuth() returned. */
function renderProvider() {
  const latest = {};
  function Probe() {
    Object.assign(latest, useAuth());
    return <p>{latest.loading ? 'checking' : latest.user ? `signed in as ${latest.user.email}` : 'signed out'}</p>;
  }
  render(<AuthProvider><Probe /></AuthProvider>);
  return latest;
}

test('on load it asks /me, and a signed-in session becomes the user', async () => {
  authApi.me.mockResolvedValue(DEMO);
  renderProvider();

  expect(screen.getByText('checking')).toBeTruthy();
  expect(await screen.findByText('signed in as demo@cadence.local')).toBeTruthy();
});

test('a 401 from /me is just "signed out", not an error', async () => {
  authApi.me.mockRejectedValue(apiError('unauthorized'));
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  renderProvider();

  expect(await screen.findByText('signed out')).toBeTruthy();
  expect(consoleError).not.toHaveBeenCalled();
});

test('any other /me failure is logged, and the app carries on signed out', async () => {
  authApi.me.mockRejectedValue(apiError('network_error'));
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  renderProvider();

  expect(await screen.findByText('signed out')).toBeTruthy();
  expect(consoleError).toHaveBeenCalledTimes(1);
});

test('login signs in and returns the user; a failed login throws and stays signed out', async () => {
  authApi.me.mockRejectedValue(apiError('unauthorized'));
  const auth = renderProvider();
  await screen.findByText('signed out');

  authApi.login.mockRejectedValueOnce(apiError('invalid_credentials', 'Wrong email or password.'));
  await act(() => expect(auth.login({ email: DEMO.email, password: 'nope' })).rejects.toThrow('Wrong email or password.'));
  expect(screen.getByText('signed out')).toBeTruthy();

  authApi.login.mockResolvedValueOnce(DEMO);
  let returned;
  await act(async () => { returned = await auth.login({ email: DEMO.email, password: 'demo1234' }); });

  expect(returned).toEqual(DEMO);
  expect(authApi.login).toHaveBeenLastCalledWith({ email: DEMO.email, password: 'demo1234' });
  expect(screen.getByText('signed in as demo@cadence.local')).toBeTruthy();
});

test('register signs you in as well', async () => {
  authApi.me.mockRejectedValue(apiError('unauthorized'));
  authApi.register.mockResolvedValue(DEMO);
  const auth = renderProvider();
  await screen.findByText('signed out');

  await act(() => auth.register({ email: DEMO.email, password: 'demo1234', displayName: 'Demo User' }));

  expect(screen.getByText('signed in as demo@cadence.local')).toBeTruthy();
});

test('logout signs out, and still does when the request fails', async () => {
  authApi.me.mockResolvedValue(DEMO);
  const auth = renderProvider();
  await screen.findByText('signed in as demo@cadence.local');

  authApi.logout.mockRejectedValueOnce(apiError('network_error'));
  await act(() => expect(auth.logout()).rejects.toThrow());

  expect(screen.getByText('signed out')).toBeTruthy();
});

test('expireSession signs out at once, with no request', async () => {
  authApi.me.mockResolvedValue(DEMO);
  const auth = renderProvider();
  await screen.findByText('signed in as demo@cadence.local');

  act(() => auth.expireSession());

  expect(screen.getByText('signed out')).toBeTruthy();
  expect(authApi.logout).not.toHaveBeenCalled();
});
