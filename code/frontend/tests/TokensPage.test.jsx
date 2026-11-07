// @vitest-environment jsdom
//
// The access tokens page with a fake API in place of fetch.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { TokensView, claudeCodeCommand, mcpConfig } from '../src/pages/TokensPage.jsx';
import { createTokensApi } from '../src/api/tokens.js';

// Vitest's globals are off and React Testing Library can't find afterEach by itself.
afterEach(cleanup);

const URL = 'https://cadence.example/api/mcp';
const CLI = { id: 1, name: 'CLI', created_at: '2026-11-01T00:00:00Z', last_used_at: null };

function renderView(api) {
  render(<TokensView api={api} serverUrl={URL} />);
}

test('the API client calls the token routes', async () => {
  const request = vi.fn().mockResolvedValue(null);
  const api = createTokensApi(request);

  await api.listTokens();
  await api.createToken('Claude');
  await api.revokeToken(7);
  await api.listApps();
  await api.disconnectApp('abc');

  expect(request.mock.calls).toEqual([
    ['/api/tokens'],
    ['/api/tokens', { method: 'POST', body: { name: 'Claude', expires_in_days: 90 } }],
    ['/api/tokens/7', { method: 'DELETE' }],
    ['/api/oauth/apps'],
    ['/api/oauth/apps/abc', { method: 'DELETE' }],
  ]);
});

test('the config points an MCP client at the server with the token', () => {
  expect(JSON.parse(mcpConfig(URL, 'cad_x'))).toEqual({
    mcpServers: { cadence: { type: 'http', url: URL, headers: { Authorization: 'Bearer cad_x' } } },
  });
  expect(claudeCodeCommand(URL, 'cad_x')).toContain(`${URL} --header "Authorization: Bearer cad_x"`);
});

test('a new token is shown once with its config, and joins the list', async () => {
  const api = {
    listTokens: vi.fn().mockResolvedValue([]), listApps: vi.fn().mockResolvedValue([]),
    createToken: vi.fn().mockResolvedValue({ ...CLI, id: 2, name: 'Claude', token: 'cad_secret' }),
  };
  renderView(api);
  await screen.findByText('No tokens yet.');

  fireEvent.change(screen.getByLabelText('Name'), { target: { value: '  Claude ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create token' }));

  expect(await screen.findByText('cad_secret')).toBeTruthy();
  expect(api.createToken).toHaveBeenCalledWith('Claude', 90);
  expect(screen.getByText(/"Authorization": "Bearer cad_secret"/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Revoke Claude' })).toBeTruthy();
});

test('a blank name is refused without calling the API', async () => {
  const api = { listTokens: vi.fn().mockResolvedValue([]), listApps: vi.fn().mockResolvedValue([]), createToken: vi.fn() };
  renderView(api);
  await screen.findByText('No tokens yet.');

  fireEvent.click(screen.getByRole('button', { name: 'Create token' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Give the token a name.');
  expect(api.createToken).not.toHaveBeenCalled();
});

test('revoking a token removes it from the list', async () => {
  const api = {
    listTokens: vi.fn().mockResolvedValue([CLI]), listApps: vi.fn().mockResolvedValue([]),
    revokeToken: vi.fn().mockResolvedValue(null),
  };
  renderView(api);
  expect(await screen.findByText('Never used', { exact: false })).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Revoke CLI' }));
  expect(api.revokeToken).not.toHaveBeenCalled();  // it asks first
  fireEvent.click(screen.getByRole('button', { name: 'Revoke token' }));

  expect(await screen.findByText('No tokens yet.')).toBeTruthy();
  expect(api.revokeToken).toHaveBeenCalledWith(1);
});

const CLAUDE = { client_id: 'abc', name: 'Claude', connected_at: '2026-11-01T00:00:00Z', last_used_at: '2026-11-02T00:00:00Z' };

test('a connected app is listed and can be disconnected', async () => {
  const api = {
    listTokens: vi.fn().mockResolvedValue([]),
    listApps: vi.fn().mockResolvedValue([CLAUDE]),
    disconnectApp: vi.fn().mockResolvedValue(null),
  };
  renderView(api);
  expect(await screen.findByText('Claude')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Disconnect Claude' }));

  expect(await screen.findByText(/No apps connected/)).toBeTruthy();
  expect(api.disconnectApp).toHaveBeenCalledWith('abc');
});

test('a failed disconnect keeps the app and says why', async () => {
  const api = {
    listTokens: vi.fn().mockResolvedValue([]),
    listApps: vi.fn().mockResolvedValue([CLAUDE]),
    disconnectApp: vi.fn().mockRejectedValue(new Error('Server error')),
  };
  renderView(api);
  await screen.findByText('Claude');

  fireEvent.click(screen.getByRole('button', { name: 'Disconnect Claude' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Server error');
  expect(screen.getByText('Claude')).toBeTruthy();
});

test('a token can be made to never expire, and keeping it cancels a revoke', async () => {
  const api = {
    listTokens: vi.fn().mockResolvedValue([{ ...CLI, expires_at: '2027-02-01T00:00:00Z' }]),
    listApps: vi.fn().mockResolvedValue([]),
    createToken: vi.fn().mockResolvedValue({ ...CLI, id: 2, name: 'CI', token: 'cad_ci' }),
    revokeToken: vi.fn(),
  };
  renderView(api);
  expect(await screen.findByText(/· Expires /)).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Revoke CLI' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep token' }));
  expect(screen.getByRole('button', { name: 'Revoke CLI' })).toBeTruthy();
  expect(api.revokeToken).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'CI' } });
  fireEvent.change(screen.getByLabelText('Expires after'), { target: { value: 'never' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create token' }));

  expect(await screen.findByText('cad_ci')).toBeTruthy();
  expect(api.createToken).toHaveBeenCalledWith('CI', null);
});
