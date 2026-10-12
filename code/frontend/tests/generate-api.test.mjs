// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { test } from 'vitest';
import assert from 'node:assert/strict';
import { createGenerateApi } from '../src/api/generate.js';

test('all three generate operations use the agreed API paths, methods and bodies', async () => {
  const calls = [];
  const api = createGenerateApi(async (...args) => { calls.push(args); });
  const body = { mode: 'prompt', count: 10, prompt: 'The bones of the human hand' };

  await api.generate(3, body);
  await api.acceptCards(7, [0, 2]);
  await api.rejectCards(7, [1]);

  assert.deepEqual(calls, [
    ['/api/decks/3/generate', { method: 'POST', body }],
    ['/api/generations/7/accept', { method: 'POST', body: { indexes: [0, 2] } }],
    ['/api/generations/7/reject', { method: 'POST', body: { indexes: [1] } }],
  ]);
});

test('ids from the route are encoded into the path', async () => {
  const calls = [];
  const api = createGenerateApi(async (path) => { calls.push(path); });

  await api.generate('3/../4', { mode: 'suggest', count: 5 });
  await api.acceptCards('7?x', [0]);

  assert.deepEqual(calls, ['/api/decks/3%2F..%2F4/generate', '/api/generations/7%3Fx/accept']);
});

test('the generate adapter passes server errors through unchanged', async () => {
  const limited = Object.assign(new Error('You have reached the limit.'), { code: 'rate_limited' });
  const api = createGenerateApi(async () => { throw limited; });

  await assert.rejects(api.generate(3, { mode: 'suggest', count: 5 }), (error) => error === limited);
});
