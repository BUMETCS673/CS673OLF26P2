/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   API client development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

// AI card generation's three endpoints: generate a batch (B3), then accept or reject its
// cards (B4). Built like createStudyApi, so it can be tested without fetch: request(path,
// { method, body }) must return parsed JSON and reject with an Error carrying the API's
// code and message. See C7 in code/plans/ITERATION_3_PLAN.md.
export function createGenerateApi(request) {
  const id = (value) => encodeURIComponent(value);
  return {
    generate: (deckId, body) =>
      request(`/api/decks/${id(deckId)}/generate`, { method: 'POST', body }),
    acceptCards: (generationId, indexes) =>
      request(`/api/generations/${id(generationId)}/accept`, { method: 'POST', body: { indexes } }),
    rejectCards: (generationId, indexes) =>
      request(`/api/generations/${id(generationId)}/reject`, { method: 'POST', body: { indexes } }),
  };
}
