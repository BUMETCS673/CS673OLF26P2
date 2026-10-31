import { pathId as id } from './request.js';

// Leech Doctor's endpoints. Built like createGenerateApi, so it can be tested without fetch.
export function createLeechesApi(request) {
  return {
    refreshSuggestions: () => request('/api/leech-suggestions/refresh', { method: 'POST' }),
    getDeckReview: (deckId) => request(`/api/decks/${id(deckId)}/leech-review`),
    submitDecisions: (reviewId, decisions) =>
      request(`/api/leech-reviews/${id(reviewId)}/decisions`, { method: 'POST', body: { decisions } }),
  };
}
