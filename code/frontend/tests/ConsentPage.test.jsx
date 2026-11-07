// @vitest-environment jsdom
//
// The OAuth consent page, with a fake API and a fake redirect.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConsentView } from '../src/pages/ConsentPage.jsx';
import { createOAuthApi } from '../src/api/oauth.js';

afterEach(cleanup);

const CONSENT = { client_name: 'Claude', redirect_host: 'claude.ai' };

function renderView(api) {
  const leave = vi.fn();
  render(<ConsentView api={api} requestId="abc" leave={leave} />);
  return leave;
}

test('the API client calls the consent routes', async () => {
  const request = vi.fn().mockResolvedValue(null);
  const api = createOAuthApi(request);

  await api.getConsent('abc');
  await api.decide('abc', true);

  expect(request.mock.calls).toEqual([
    ['/api/oauth/consent/abc'],
    ['/api/oauth/consent/abc', { method: 'POST', body: { approve: true } }],
  ]);
});

test.each([['Allow', true], ['Deny', false]])('%s sends the answer and goes back to the app', async (label, approve) => {
  const api = {
    getConsent: vi.fn().mockResolvedValue(CONSENT),
    decide: vi.fn().mockResolvedValue({ redirect_url: 'https://claude.ai/callback?code=x' }),
  };
  const leave = renderView(api);

  expect(await screen.findByText('Allow Claude to use your Cadence account?')).toBeTruthy();
  expect(screen.getByText(/back to claude\.ai/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: label }));

  await vi.waitFor(() => expect(leave).toHaveBeenCalledWith('https://claude.ai/callback?code=x'));
  expect(api.decide).toHaveBeenCalledWith('abc', approve);
});

test('an expired request says so', async () => {
  const api = { getConsent: vi.fn().mockRejectedValue(new Error('This sign-in request has expired.')) };
  renderView(api);

  expect((await screen.findByRole('alert')).textContent).toBe('This sign-in request has expired.');
});

test('a failed answer shows an error and lets the user try again', async () => {
  const api = {
    getConsent: vi.fn().mockResolvedValue(CONSENT),
    decide: vi.fn().mockRejectedValue(new Error('Network down')),
  };
  const leave = renderView(api);
  await screen.findByText('Allow Claude to use your Cadence account?');

  fireEvent.click(screen.getByRole('button', { name: 'Allow' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Network down');
  expect(screen.getByRole('button', { name: 'Allow' }).disabled).toBe(false);
  expect(leave).not.toHaveBeenCalled();
});
