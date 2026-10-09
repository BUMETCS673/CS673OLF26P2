// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import { createAuthenticatedGenerateApi } from '../src/api/generate.client.js';

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

const GENERATION = {
  id: 7, deck_id: 3, mode: 'prompt', requested_count: 1, model: 'fake',
  created_at: '2026-10-09T14:00:00Z',
  cards: [{ index: 0, front: 'Sample question 1', back: 'Sample answer 1', status: 'pending' }],
};

test('generate is a POST to /api/decks/:id/generate with the session cookie and the body', async () => {
  const calls = mockFetch(() => json(GENERATION, 201));
  const api = createAuthenticatedGenerateApi(() => {});
  const body = { mode: 'prompt', count: 1, prompt: 'Capitals' };

  assert.deepEqual(await api.generate(3, body), GENERATION);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/decks/3/generate');
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].credentials, 'include');
  assert.equal(calls[0].headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].body), body);
});

test('acceptCards and rejectCards POST the indexes to the generation', async () => {
  const calls = mockFetch(() => json(GENERATION));
  const api = createAuthenticatedGenerateApi(() => {});

  await api.acceptCards(7, [0, 2]);
  await api.rejectCards(7, [1]);

  assert.deepEqual(calls.map((call) => [call.url, call.method, JSON.parse(call.body)]), [
    ['/api/generations/7/accept', 'POST', { indexes: [0, 2] }],
    ['/api/generations/7/reject', 'POST', { indexes: [1] }],
  ]);
});

test('a 429 rejects with code rate_limited and keeps the learner signed in', async () => {
  let expirations = 0;
  const api = createAuthenticatedGenerateApi(() => { expirations += 1; });
  mockFetch(() => apiError(429, 'rate_limited', 'You have reached the limit.'));

  await assert.rejects(api.generate(3, { mode: 'suggest', count: 5 }), {
    status: 429, code: 'rate_limited', message: 'You have reached the limit.',
  });
  assert.equal(expirations, 0);
});

test('a 401 signs the learner out and still rejects, for every operation', async () => {
  let expirations = 0;
  const api = createAuthenticatedGenerateApi(() => { expirations += 1; });
  mockFetch(() => apiError(401, 'unauthorized', 'Authentication required.'));

  await assert.rejects(api.generate(3, { mode: 'suggest', count: 5 }), { status: 401, code: 'unauthorized' });
  await assert.rejects(api.acceptCards(7, [0]), { status: 401, code: 'unauthorized' });
  await assert.rejects(api.rejectCards(7, [0]), { status: 401, code: 'unauthorized' });
  assert.equal(expirations, 3);
});
