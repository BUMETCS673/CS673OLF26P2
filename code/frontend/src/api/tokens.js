import { pathId as id } from './request.js';

// Personal access tokens that let an MCP client like Claude act for this account.
export function createTokensApi(request) {
  return {
    listTokens: () => request('/api/tokens'),
    // expiresInDays is null for a token that never expires
    createToken: (name, expiresInDays = 90) =>
      request('/api/tokens', { method: 'POST', body: { name, expires_in_days: expiresInDays } }),
    revokeToken: (tokenId) => request(`/api/tokens/${id(tokenId)}`, { method: 'DELETE' }),
    // apps like Claude or ChatGPT that connected over OAuth instead of with a token
    listApps: () => request('/api/oauth/apps'),
    disconnectApp: (clientId) => request(`/api/oauth/apps/${id(clientId)}`, { method: 'DELETE' }),
  };
}
