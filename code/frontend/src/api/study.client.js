import { requestApi, withSessionExpiry } from './request.js';
import { createStudyApi } from './study.js';

// The study endpoints on WS3's client. A 401 calls onUnauthorized, the same as the deck
// and card operations, so an expired session ends a study session too.
export function createAuthenticatedStudyApi(onUnauthorized) {
  return createStudyApi(withSessionExpiry(requestApi, onUnauthorized));
}
