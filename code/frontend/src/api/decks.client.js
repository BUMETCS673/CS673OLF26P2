import { get, post, patch, del } from './client.js';
import { createDecksApi } from './decks.js';

// WS3 owns fetch, cookies, serialization and errors. Its helpers add /api.
export const decksApi = createDecksApi((path, { method = 'GET', body } = {}) => {
  const relativePath = path.slice('/api'.length);
  switch (method) {
    case 'GET': return get(relativePath);
    case 'POST': return post(relativePath, body);
    case 'PATCH': return patch(relativePath, body);
    case 'DELETE': return del(relativePath);
    default: throw new Error(`Unsupported deck request method: ${method}`);
  }
});
