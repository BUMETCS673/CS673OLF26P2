/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   API client development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

// Study mode's two endpoints: Lab 3's due cards (story 2) and saving a review (story 5).
// Built like createDecksApi, so it can be tested without fetch: request(path,
// { method, body }) must return parsed JSON and reject with an Error carrying the API's
// code and message. See "Frontend contracts" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
export function createStudyApi(request) {
  const id = (value) => encodeURIComponent(value);
  return {
    getDueCards: (deckId) => request(`/api/decks/${id(deckId)}/due`),
    reviewCard: (cardId, rating) =>
      request(`/api/cards/${id(cardId)}/review`, { method: 'POST', body: { rating } }),
  };
}
