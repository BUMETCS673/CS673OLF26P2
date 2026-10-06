// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { test } from 'vitest';
import assert from 'node:assert/strict';
import { createStudyApi } from '../src/api/study.js';

test('both study operations use the agreed API paths, methods and bodies', async () => {
  const calls = [];
  const api = createStudyApi(async (...args) => { calls.push(args); });
  await api.getDueCards(3);
  await api.reviewCard(9, 'good');
  assert.deepEqual(calls, [
    ['/api/decks/3/due'],
    ['/api/cards/9/review', { method: 'POST', body: { rating: 'good' } }],
  ]);
});

test('ids from the route are encoded into the path', async () => {
  const calls = [];
  const api = createStudyApi(async (path) => { calls.push(path); });
  await api.getDueCards('3/../4');
  assert.deepEqual(calls, ['/api/decks/3%2F..%2F4/due']);
});

test('the study adapter passes server errors through unchanged', async () => {
  const conflict = Object.assign(new Error("Card isn't due yet"), { code: 'conflict' });
  const api = createStudyApi(async () => { throw conflict; });
  await assert.rejects(api.reviewCard(9, 'good'), (error) => error === conflict);
});
