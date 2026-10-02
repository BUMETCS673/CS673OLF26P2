import { createDecksApi } from './decks.js';
import { requestApi, withSessionExpiry } from './request.js';

// WS4's nine operations on WS3's client. The transport and the 401 handling live in
// request.js, which study.client.js shares.
export const decksApi = createDecksApi(requestApi);

export function createAuthenticatedDecksApi(onUnauthorized) {
  return createDecksApi(withSessionExpiry(requestApi, onUnauthorized));
}
