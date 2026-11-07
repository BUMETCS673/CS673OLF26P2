import { pathId as id } from './request.js';

// The consent step when an MCP client such as Claude or ChatGPT signs in over OAuth.
export function createOAuthApi(request) {
  return {
    getConsent: (requestId) => request(`/api/oauth/consent/${id(requestId)}`),
    decide: (requestId, approve) =>
      request(`/api/oauth/consent/${id(requestId)}`, { method: 'POST', body: { approve } }),
  };
}
