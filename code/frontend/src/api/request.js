/*
 * Step 0b: requestApi() and withSessionExpiry(), moved here from WS4's
 * decks.client.js so the study client could share them.
 * AI Utilization: ~100% of that refactor
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 *
 * Iteration 3 refactor: requestApi() passes straight to client.js's request(), and
 * createAuthenticatedApi() and pathId() replace the per-API client files and helpers.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { request } from './client.js';

// The API factories build full /api paths; client.js adds the /api prefix itself.
export function requestApi(path, options) {
  return request(path.slice('/api'.length), options);
}

export function withSessionExpiry(request, onUnauthorized) {
  return async (path, options) => {
    try {
      return await request(path, options);
    } catch (error) {
      if (error.code === 'unauthorized' || error.status === 401) onUnauthorized();
      throw error;
    }
  };
}

// createApi is one of the factories (createDecksApi, createStudyApi, createGenerateApi).
export function createAuthenticatedApi(createApi, onUnauthorized) {
  return createApi(withSessionExpiry(requestApi, onUnauthorized));
}

export const pathId = (value) => encodeURIComponent(value);
