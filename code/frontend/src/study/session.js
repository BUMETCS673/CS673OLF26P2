/**
 * The study session reducer (Lab 3, Story 3). It decides which card is showing; it never
 * computes intervals (the backend does), renders anything, or calls the API.
 *
 * State shape:
 *   {
 *     learning: Card[],        // learning and relearning cards waiting, sorted by due_at
 *     main: Card[],            // review cards, then new cards, in the order they'll show
 *     current: Card | null,    // the card showing, taken out of whichever queue it was in
 *     revealed: boolean,       // whether the current card's answer is showing
 *     finished: boolean,       // nothing left to show in this session
 *     counts: { again, hard, good, easy },  // answers given this session, per rating
 *     nextLearningDue: string | null,       // when finished: due_at of the next learning card
 *     lastAnsweredId: number | null,        // the card answered last, to avoid repeating it
 *   }
 *
 * `now` is always milliseconds (Date.now()), passed in by the caller.
 */

/** The first state for a session over `due`, the GET /api/decks/:id/due response. */
// eslint-disable-next-line no-unused-vars
export function initSession({ due, now }) {
  return {
    learning: [],
    main: [],
    current: null,
    revealed: false,
    finished: false,
    counts: { again: 0, hard: 0, good: 0, easy: 0 },
    nextLearningDue: null,
    lastAnsweredId: null,
  };
}

/** Handles `reveal`, `answered`, and `skipped`. Never mutates `state`. */
// eslint-disable-next-line no-unused-vars
export function sessionReducer(state, action) {
  return state;
}
