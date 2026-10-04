import { get, post, patch, del } from './client.js';

// The transport the endpoint modules (decks.js, study.js) are built on. They write full
// /api/... paths; WS3's client owns fetch, cookies, serialization and errors, and its
// helpers add /api themselves, so it comes off here.
export function requestApi(path, { method = 'GET', body } = {}) {
  const relativePath = path.slice('/api'.length);
  switch (method) {
    case 'GET': return get(relativePath);
    case 'POST': return post(relativePath, body);
    case 'PATCH': return patch(relativePath, body);
    case 'DELETE': return del(relativePath);
    default: throw new Error(`Unsupported request method: ${method}`);
  }
}

// Handle expiration for every operation, including saves caught inside forms.
// Re-throw so a failed mutation never continues along its success path.
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
