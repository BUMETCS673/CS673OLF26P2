import { pathId as id } from './request.js';

// The deck tutor's endpoints. Built like createGenerateApi, so it can be tested without fetch.
export function createTutorApi(request) {
  return {
    getTutor: (deckId) => request(`/api/decks/${id(deckId)}/tutor`),
    sendMessage: (deckId, text) =>
      request(`/api/decks/${id(deckId)}/tutor/messages`, { method: 'POST', body: { text } }),
    decideProposal: (deckId, proposalId, accept) =>
      request(`/api/decks/${id(deckId)}/tutor/proposal`, {
        method: 'POST',
        body: { proposal_id: proposalId, accept },
      }),
    resetTutor: (deckId) => request(`/api/decks/${id(deckId)}/tutor`, { method: 'DELETE' }),
  };
}
