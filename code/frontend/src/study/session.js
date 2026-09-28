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

import { LEARN_AHEAD_MS, RATINGS } from './constants.js';

const dueMs = (card) => Date.parse(card.due_at);

/** A copy of `queue` with `card` inserted by due_at, after any cards due at the same time. */
function insertByDue(queue, card) {
  const index = queue.findIndex((other) => dueMs(other) > dueMs(card));
  return index === -1 ? [...queue, card] : [...queue.slice(0, index), card, ...queue.slice(index)];
}

/**
 * `state` with the next card showing (Anki's order): a learning card due now, else the next
 * main-queue card, else a learning card within the learn-ahead limit, else finished. When only
 * learning cards are left, the card just answered isn't shown again straight away if another
 * one can be shown instead.
 */
function pickNext(state, now) {
  const { learning, main, lastAnsweredId } = state;
  const showing = { ...state, revealed: false, finished: false, nextLearningDue: null };

  if (learning.length > 0 && dueMs(learning[0]) <= now) {
    return { ...showing, current: learning[0], learning: learning.slice(1) };
  }
  if (main.length > 0) {
    return { ...showing, current: main[0], main: main.slice(1) };
  }
  const ahead = learning.filter((card) => dueMs(card) <= now + LEARN_AHEAD_MS);
  if (ahead.length > 0) {
    const pick = ahead.find((card) => card.id !== lastAnsweredId) ?? ahead[0];
    return { ...showing, current: pick, learning: learning.filter((card) => card !== pick) };
  }
  return {
    ...state,
    current: null,
    revealed: false,
    finished: true,
    nextLearningDue: learning.length > 0 ? learning[0].due_at : null,
  };
}

/** The first state for a session over `due`, the GET /api/decks/:id/due response. */
export function initSession({ due, now }) {
  const state = {
    learning: [...due.learning].sort((a, b) => dueMs(a) - dueMs(b)),
    main: [...due.review, ...due.new],
    current: null,
    revealed: false,
    finished: false,
    counts: Object.fromEntries(RATINGS.map((rating) => [rating, 0])),
    nextLearningDue: null,
    lastAnsweredId: null,
  };
  return pickNext(state, now);
}

/** Handles `reveal`, `answered`, and `skipped`. Never mutates `state`. */
export function sessionReducer(state, action) {
  switch (action.type) {
    case 'reveal':
      return state.current && !state.revealed ? { ...state, revealed: true } : state;

    case 'answered': {
      if (!state.current || !state.revealed) return state;
      const { card, rating, now } = action;
      const stillLearning = card.state === 'learning' || card.state === 'relearning';
      return pickNext(
        {
          ...state,
          learning: stillLearning ? insertByDue(state.learning, card) : state.learning,
          counts: { ...state.counts, [rating]: state.counts[rating] + 1 },
          lastAnsweredId: card.id,
        },
        now,
      );
    }

    case 'skipped':
      return state.current ? pickNext({ ...state, lastAnsweredId: state.current.id }, action.now) : state;

    default:
      return state;
  }
}
