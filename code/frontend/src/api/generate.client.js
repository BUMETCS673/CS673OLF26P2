/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   API client development
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { createGenerateApi } from './generate.js';
import { requestApi, withSessionExpiry } from './request.js';

// The generate endpoints on WS3's client. A 401 calls onUnauthorized, the same as the deck
// and study operations, so an expired session ends a generation too.
export function createAuthenticatedGenerateApi(onUnauthorized) {
  return createGenerateApi(withSessionExpiry(requestApi, onUnauthorized));
}
