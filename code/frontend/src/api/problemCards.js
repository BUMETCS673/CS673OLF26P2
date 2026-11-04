import { pathId as id } from './request.js';

// Problem Cards' endpoints. Built like createGenerateApi, so it can be tested without fetch.
export function createProblemCardsApi(request) {
  return {
    getSuggestions: () => request('/api/problem-cards'),
    getDeckReview: (deckId) => request(`/api/decks/${id(deckId)}/problem-card-review`),
    submitDecisions: (reviewId, decisions) =>
      request(`/api/problem-card-reviews/${id(reviewId)}/decisions`, { method: 'POST', body: { decisions } }),
  };
}
