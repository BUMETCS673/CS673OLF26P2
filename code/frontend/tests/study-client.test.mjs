import { afterEach, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import { createAuthenticatedStudyApi } from '../src/api/study.client.js';

// Each test replaces fetch with a spy; put the real one back afterwards.
afterEach(() => { vi.restoreAllMocks(); });

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const apiError = (status, code, message) => json({ error: { code, message } }, status);

/** Replaces fetch with `respond`, and returns the list each call is recorded in. */
function mockFetch(respond) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    calls.push({ url, ...options });
    return respond(url, options);
  });
  return calls;
}

test('getDueCards is a GET to /api/decks/:id/due with the session cookie', async () => {
  const due = { learning: [], review: [], new: [{ id: 9, state: 'new', due_at: null }] };
  const calls = mockFetch(() => json(due));
  const api = createAuthenticatedStudyApi(() => {});

  assert.deepEqual(await api.getDueCards(3), due);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/decks/3/due');
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].credentials, 'include');
});

test('reviewCard is a POST to /api/cards/:id/review with the rating as JSON', async () => {
  const saved = { id: 9, state: 'learning', due_at: '2026-10-01T14:10:00Z' };
  const calls = mockFetch(() => json(saved));
  const api = createAuthenticatedStudyApi(() => {});

  assert.deepEqual(await api.reviewCard(9, 'good'), saved);
  assert.equal(calls[0].url, '/api/cards/9/review');
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].credentials, 'include');
  assert.equal(calls[0].headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].body), { rating: 'good' });
});

test('a 409 rejects with code conflict and keeps the learner signed in', async () => {
  let expirations = 0;
  const api = createAuthenticatedStudyApi(() => { expirations += 1; });
  mockFetch(() => apiError(409, 'conflict', "Card isn't due yet"));

  await assert.rejects(api.reviewCard(9, 'good'), { status: 409, code: 'conflict' });
  assert.equal(expirations, 0);
});

test('a 401 signs the learner out and still rejects, for both operations', async () => {
  let expirations = 0;
  const api = createAuthenticatedStudyApi(() => { expirations += 1; });
  mockFetch(() => apiError(401, 'unauthorized', 'Authentication required.'));

  await assert.rejects(api.getDueCards(3), { status: 401, code: 'unauthorized' });
  assert.equal(expirations, 1);
  await assert.rejects(api.reviewCard(9, 'good'), { status: 401, code: 'unauthorized' });
  assert.equal(expirations, 2);
});
