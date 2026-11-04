import { pathId as id } from './request.js';

// Uploaded study materials. Built like createGenerateApi, so it can be tested without fetch.
export function createMaterialsApi(request) {
  return {
    upload: (file) => {
      const body = new FormData();
      body.append('file', file);
      return request('/api/materials', { method: 'POST', body });
    },
    getMaterial: (documentId) => request(`/api/materials/${id(documentId)}`),
  };
}
