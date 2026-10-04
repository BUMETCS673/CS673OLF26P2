/*
 * Step 0b: moved the transport and the 401 handling from here to request.js.
 * AI Utilization: ~100% of that refactor
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { createDecksApi } from './decks.js';
import { requestApi, withSessionExpiry } from './request.js';

// WS4's nine operations on WS3's client. The transport and the 401 handling live in
// request.js, which study.client.js shares.
export const decksApi = createDecksApi(requestApi);

export function createAuthenticatedDecksApi(onUnauthorized) {
  return createDecksApi(withSessionExpiry(requestApi, onUnauthorized));
}
