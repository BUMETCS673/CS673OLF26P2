import { test } from 'vitest';
import assert from 'node:assert/strict';
import { initSession, sessionReducer } from '../src/study/session.js';

const NOW = Date.parse('2026-10-01T14:00:00Z');
const MINUTE = 60 * 1000;

/** An ISO due time `minutes` from NOW. */
const at = (minutes) => new Date(NOW + minutes * MINUTE).toISOString();

const newCard = (id) => ({ id, state: 'new', due_at: null });
const reviewCard = (id, dueInMinutes = 0) => ({ id, state: 'review', due_at: at(dueInMinutes) });
const learningCard = (id, dueInMinutes) => ({ id, state: 'learning', due_at: at(dueInMinutes) });

/** Freezes `value` all the way down, so any mutation by the reducer throws. */
function deepFreeze(value) {
  for (const inner of Object.values(value)) {
    if (inner && typeof inner === 'object') deepFreeze(inner);
  }
  return Object.freeze(value);
}

const start = (due, now = NOW) =>
  deepFreeze(initSession({ due: { learning: [], review: [], new: [], ...due }, now }));
const reveal = (state) => deepFreeze(sessionReducer(state, { type: 'reveal' }));
const answer = (state, rating, card, now = NOW) =>
  deepFreeze(sessionReducer(state, { type: 'answered', rating, card, now }));
const skip = (state, now = NOW) => deepFreeze(sessionReducer(state, { type: 'skipped', now }));

const ids = (cards) => cards.map((card) => card.id);

test('1 review card and 2 new cards: the review card is showing, not revealed', () => {
  const state = start({ review: [reviewCard(1)], new: [newCard(2), newCard(3)] });
  assert.equal(state.current.id, 1);
  assert.equal(state.revealed, false);
  assert.equal(state.finished, false);
  assert.deepEqual(ids(state.main), [2, 3]);
});

test('reveal shows the answer of the current card', () => {
  const state = reveal(start({ new: [newCard(1)] }));
  assert.equal(state.current.id, 1);
  assert.equal(state.revealed, true);
});

test('a card showing, not revealed: answered good changes nothing', () => {
  const state = start({ new: [newCard(1), newCard(2)] });
  const next = answer(state, 'good', { ...newCard(1), state: 'learning', due_at: at(10) });
  assert.deepEqual(next, state);
});

test('reveal with nothing showing changes nothing', () => {
  const state = start({});
  assert.equal(state.finished, true);
  assert.deepEqual(reveal(state), state);
});

test('a revealed new card answered good comes back as learning: the next main-queue card shows', () => {
  const state = reveal(start({ new: [newCard(1), newCard(2)] }));
  const next = answer(state, 'good', { ...newCard(1), state: 'learning', due_at: at(10) });
  assert.equal(next.current.id, 2);
  assert.equal(next.revealed, false);
  assert.deepEqual(ids(next.learning), [1]);
  assert.deepEqual(next.main, []);
});

test('a learning card due now, with main-queue cards left: the learning card shows first', () => {
  const state = start({ learning: [learningCard(1, 0)], review: [reviewCard(2)] });
  assert.equal(state.current.id, 1);
  assert.deepEqual(ids(state.main), [2]);
});

test('main queue empty, learning cards A and B waiting: A answered again shows B next, not A', () => {
  const state = reveal(start({ learning: [learningCard(1, 0), learningCard(2, 5)] }));
  const next = answer(state, 'again', learningCard(1, 1));
  assert.equal(next.current.id, 2);
  assert.deepEqual(ids(next.learning), [1]);
});

test('main queue empty, one learning card due in 15m: it shows (learn ahead)', () => {
  const state = start({ learning: [learningCard(1, 15)] });
  assert.equal(state.current.id, 1);
  assert.equal(state.finished, false);
});

test('main queue empty, one learning card due in 25m: finished, with the next due time set', () => {
  const state = start({ learning: [learningCard(1, 25)] });
  assert.equal(state.current, null);
  assert.equal(state.finished, true);
  assert.equal(state.nextLearningDue, at(25));
});

test('a revealed review card answered good comes back as review: it leaves the session', () => {
  const state = reveal(start({ review: [reviewCard(1), reviewCard(2)] }));
  const next = answer(state, 'good', reviewCard(1, 25 * 24 * 60));
  assert.equal(next.current.id, 2);
  assert.deepEqual(next.learning, []);
  assert.deepEqual(next.main, []);
});

test('the last card answered: finished, with the right counts', () => {
  let state = reveal(start({ review: [reviewCard(1), reviewCard(2)] }));
  state = reveal(answer(state, 'hard', reviewCard(1, 12 * 24 * 60)));
  state = answer(state, 'good', reviewCard(2, 25 * 24 * 60));
  assert.equal(state.current, null);
  assert.equal(state.finished, true);
  assert.deepEqual(state.counts, { again: 0, hard: 1, good: 1, easy: 0 });
  assert.equal(state.nextLearningDue, null);
});

test('a card showing, skipped: the next card shows, and the counts do not change', () => {
  const state = start({ review: [reviewCard(1), reviewCard(2)] });
  const next = skip(state);
  assert.equal(next.current.id, 2);
  assert.equal(next.revealed, false);
  assert.deepEqual(next.counts, { again: 0, hard: 0, good: 0, easy: 0 });
});
