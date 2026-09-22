// WS4: inject WS3's shared client here. Pages never call fetch themselves.
// request(path, { method, body }) must return parsed JSON (or undefined for 204)
// and reject with an Error carrying the API's code and message.
export function createDecksApi(request) {
  const id = (value) => encodeURIComponent(value);
  return {
    listDecks: () => request('/api/decks'),
    createDeck: (body) => request('/api/decks', { method: 'POST', body }),
    getDeck: (deckId) => request(`/api/decks/${id(deckId)}`),
    updateDeck: (deckId, body) => request(`/api/decks/${id(deckId)}`, { method: 'PATCH', body }),
    deleteDeck: (deckId) => request(`/api/decks/${id(deckId)}`, { method: 'DELETE' }),
    listCards: (deckId) => request(`/api/decks/${id(deckId)}/cards`),
    createCard: (deckId, body) => request(`/api/decks/${id(deckId)}/cards`, { method: 'POST', body }),
    updateCard: (cardId, body) => request(`/api/cards/${id(cardId)}`, { method: 'PATCH', body }),
    deleteCard: (cardId) => request(`/api/cards/${id(cardId)}`, { method: 'DELETE' }),
  };
}
