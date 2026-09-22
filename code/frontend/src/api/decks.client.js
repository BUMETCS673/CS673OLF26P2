import { get, post, patch, del } from './client.js';
import { createDecksApi } from './decks.js';

// WS3 owns fetch, cookies, serialization and errors. Its helpers add /api.
function requestDeck(path, { method = 'GET', body } = {}) {
  const relativePath = path.slice('/api'.length);
  switch (method) {
    case 'GET': return get(relativePath);
    case 'POST': return post(relativePath, body);
    case 'PATCH': return patch(relativePath, body);
    case 'DELETE': return del(relativePath);
    default: throw new Error(`Unsupported deck request method: ${method}`);
  }
}

export const decksApi = createDecksApi(requestDeck);

// Handle expiration for every operation, including saves caught inside forms.
// Re-throw so a failed mutation never continues along its success path.
export function createAuthenticatedDecksApi(onUnauthorized) {
  return createDecksApi(async (path, options) => {
    try {
      return await requestDeck(path, options);
    } catch (error) {
      if (error.code === 'unauthorized' || error.status === 401) onUnauthorized();
      throw error;
    }
  });
}
