// Temporary WS4 preview only. This is browser-local demo storage, not authentication.
// TODO(WS2/WS3): replace this transport with WS3's client after the endpoints land.
export const DEMO_STORAGE_KEY = 'cadence.ws4.demo.v1';

function fail(code, message) { throw Object.assign(new Error(message), { code }); }

function text(body, field, limit, required) {
  const value = body[field];
  if (value == null && !required) return '';
  if (typeof value !== 'string' || (required && !value.trim())) fail('validation_error', `${field} cannot be blank.`);
  if (value.length > limit) fail('validation_error', `${field} must be ${limit} characters or fewer.`);
  return value.trim();
}

export function createDemoRequest(storage) {
  const emptyState = () => ({ nextId: 1, decks: [], cards: [] });

  function validState(state) {
    if (!state || !Number.isSafeInteger(state.nextId) || state.nextId < 1 ||
        !Array.isArray(state.decks) || !Array.isArray(state.cards)) return false;
    const validId = (id) => Number.isSafeInteger(id) && id > 0 && id < state.nextId;
    const validDates = (item) => typeof item.created_at === 'string' && typeof item.updated_at === 'string';
    if (!state.decks.every((deck) => deck && validId(deck.id) &&
        typeof deck.name === 'string' && (deck.description == null || typeof deck.description === 'string') && validDates(deck))) return false;
    const deckIds = new Set(state.decks.map((deck) => deck.id));
    if (!state.cards.every((card) => card && validId(card.id) && deckIds.has(card.deck_id) &&
        typeof card.front === 'string' && typeof card.back === 'string' && validDates(card))) return false;
    const ids = [...state.decks, ...state.cards].map((item) => item.id);
    return new Set(ids).size === ids.length;
  }

  function load() {
    let saved;
    try {
      saved = storage.getItem(DEMO_STORAGE_KEY);
    } catch {
      fail('demo_storage_error', 'The browser could not read your demo data. Check that site storage is available.');
    }
    if (!saved) return emptyState();
    try {
      const state = JSON.parse(saved);
      return validState(state) ? state : emptyState();
    } catch {
      // Corrupt or obsolete demo data must not permanently block the UI. Keep the
      // original value untouched until a successful user save replaces it.
      return emptyState();
    }
  }

  function save(state) {
    try { storage.setItem(DEMO_STORAGE_KEY, JSON.stringify(state)); }
    catch { fail('demo_storage_error', 'Your browser could not save this change. Allow site storage or free some space, then try again.'); }
  }

  return async function request(path, { method = 'GET', body = {} } = {}) {
    const state = load();
    const now = new Date().toISOString();
    const deckJson = (deck) => ({ ...deck, card_count: state.cards.filter((card) => card.deck_id === deck.id).length });
    let result;
    if (path === '/api/decks') {
      if (method === 'GET') return state.decks.map(deckJson);
      if (method !== 'POST') fail('method_not_allowed', 'Method not allowed.');
      result = { id: state.nextId++, name: text(body, 'name', 120, true), description: text(body, 'description', 1000, false), created_at: now, updated_at: now };
      state.decks.push(result);
      result = deckJson(result);
    } else {
      const deckMatch = path.match(/^\/api\/decks\/(\d+)(\/cards)?$/);
      const cardMatch = path.match(/^\/api\/cards\/(\d+)$/);
      if (deckMatch) {
        const deck = state.decks.find((item) => item.id === Number(deckMatch[1]));
        if (!deck) fail('not_found', 'Deck not found.');
        if (deckMatch[2]) {
          if (method === 'GET') return state.cards.filter((card) => card.deck_id === deck.id);
          if (method !== 'POST') fail('method_not_allowed', 'Method not allowed.');
          result = { id: state.nextId++, deck_id: deck.id, front: text(body, 'front', 2000, true), back: text(body, 'back', 2000, true), created_at: now, updated_at: now };
          state.cards.push(result);
        } else if (method === 'GET') return deckJson(deck);
        else if (method === 'PATCH') {
          if ('name' in body) deck.name = text(body, 'name', 120, true);
          if ('description' in body) deck.description = text(body, 'description', 1000, false);
          deck.updated_at = now;
          result = deckJson(deck);
        } else if (method === 'DELETE') {
          state.decks = state.decks.filter((item) => item.id !== deck.id);
          state.cards = state.cards.filter((item) => item.deck_id !== deck.id);
        } else fail('method_not_allowed', 'Method not allowed.');
      } else if (cardMatch) {
        const card = state.cards.find((item) => item.id === Number(cardMatch[1]));
        if (!card) fail('not_found', 'Card not found.');
        if (method === 'PATCH') {
          if ('front' in body) card.front = text(body, 'front', 2000, true);
          if ('back' in body) card.back = text(body, 'back', 2000, true);
          card.updated_at = now;
          result = card;
        } else if (method === 'DELETE') state.cards = state.cards.filter((item) => item.id !== card.id);
        else fail('method_not_allowed', 'Method not allowed.');
      } else fail('not_found', 'Not found.');
    }
    save(state);
    return result;
  };
}
