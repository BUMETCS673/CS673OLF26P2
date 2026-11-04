// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { test } from 'vitest';
import assert from 'node:assert/strict';
import { createGenerateApi } from '../src/api/generate.js';

// Every reply the adapter reads from, so one fake can answer all of its requests.
const SERVER_REPLY = {
  job_id: 5,
  generation: undefined,
  candidates: [
    { front: 'Q1', back: 'A1', status: 'pending' },
    { front: 'Q2', back: 'A2', status: 'accepted' },
  ],
};
SERVER_REPLY.generation = SERVER_REPLY;
const DONE = async () => ({ status: 'done', result: { generation_id: 9 } });

test('all three generate operations use the agreed API paths, methods and bodies', async () => {
  const calls = [];
  const api = createGenerateApi(async (...args) => { calls.push(args); return SERVER_REPLY; }, DONE);
  const body = { mode: 'prompt', count: 10, prompt: 'The bones of the human hand' };

  await api.generate(3, body);
  await api.acceptCards(7, [0, 2]);
  await api.rejectCards(7, [1]);

  assert.deepEqual(calls, [
    ['/api/decks/3/generate', { method: 'POST', body }],
    ['/api/generations/9'],
    ['/api/generations/7/accept', { method: 'POST', body: { indexes: [0, 2] } }],
    ['/api/generations/7/reject', { method: 'POST', body: { indexes: [1] } }],
  ]);
});

test('generate waits for the job, then gives its batch with each card numbered', async () => {
  const followed = [];
  const follow = async (jobId) => { followed.push(jobId); return DONE(); };
  const api = createGenerateApi(async () => SERVER_REPLY, follow);

  const generation = await api.generate(3, { mode: 'prompt', count: 1, prompt: 'Cells' });

  assert.deepEqual(followed, [5]);
  assert.deepEqual(generation.cards, [
    { front: 'Q1', back: 'A1', status: 'pending', index: 0 },
    { front: 'Q2', back: 'A2', status: 'accepted', index: 1 },
  ]);
});

test('a failed job becomes an error that can name the field', async () => {
  const failed = async () => ({
    status: 'failed',
    error: "That file doesn't seem to cover this topic.",
    result: { field: 'topic' },
  });
  const api = createGenerateApi(async () => SERVER_REPLY, failed);

  await assert.rejects(api.generate(3, { mode: 'file' }), (error) => (
    error.message === "That file doesn't seem to cover this topic."
    && error.field === 'topic'
    && error.code === 'job_failed'
  ));
});

test('generating polls the job when the event stream is unavailable', async () => {
  const blocked = async () => {
    throw Object.assign(new Error('blocked'), { code: 'job_unavailable' });
  };
  const polled = [];
  const poll = async (jobId) => { polled.push(jobId); return DONE(); };
  const api = createGenerateApi(async () => SERVER_REPLY, blocked, poll);

  const generation = await api.generate(3, { mode: 'prompt', count: 1, prompt: 'Cells' });

  assert.deepEqual(polled, [5]);
  assert.equal(generation.cards.length, 2);
});

test('accepting numbers the cards of the generation it returns', async () => {
  const api = createGenerateApi(async () => ({ cards: [], generation: SERVER_REPLY }), DONE);

  const accepted = await api.acceptCards(7, [0]);

  assert.equal(accepted.generation.cards[1].index, 1);
});

test('suggestTopics posts to the decks suggestions, with no body', async () => {
  const calls = [];
  const api = createGenerateApi(async (...args) => { calls.push(args); });

  await api.suggestTopics(3);

  assert.deepEqual(calls, [['/api/decks/3/suggestions', { method: 'POST' }]]);
});

test('ids from the route are encoded into the path', async () => {
  const calls = [];
  const api = createGenerateApi(async (path) => { calls.push(path); return SERVER_REPLY; }, DONE);

  await api.generate('3/../4', { mode: 'suggest', count: 5 });
  await api.acceptCards('7?x', [0]);

  assert.deepEqual(calls, [
    '/api/decks/3%2F..%2F4/generate',
    '/api/generations/9',
    '/api/generations/7%3Fx/accept',
  ]);
});

test('the generate adapter passes server errors through unchanged', async () => {
  const limited = Object.assign(new Error('You have reached the limit.'), { code: 'rate_limited' });
  const api = createGenerateApi(async () => { throw limited; });

  await assert.rejects(api.generate(3, { mode: 'suggest', count: 5 }), (error) => error === limited);
});
