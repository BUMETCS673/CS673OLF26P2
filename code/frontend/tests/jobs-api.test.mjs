// Following a background job through server-sent events, with a stand-in EventSource.

import { test } from 'vitest';
import assert from 'node:assert/strict';
import { followJob, pollJob } from '../src/api/jobs.js';

class FakeEventSource {
  static CLOSED = 2;

  static last = null;

  constructor(url) {
    this.url = url;
    this.closed = false;
    this.readyState = 1;
    FakeEventSource.last = this;
  }

  addEventListener(name, listener) {
    this.name = name;
    this.listener = listener;
  }

  close() {
    this.closed = true;
  }

  send(event) {
    this.listener({ data: JSON.stringify(event) });
  }
}

const follow = (options = {}) => followJob(5, { EventSourceClass: FakeEventSource, ...options });
const noWait = async () => {};

test('without EventSource it rejects as unavailable, so the caller polls', async () => {
  await assert.rejects(follow({ EventSourceClass: null }), (error) => error.code === 'job_unavailable');
});

test('polling asks until the job finishes', async () => {
  const replies = [{ status: 'running' }, { status: 'done', result: { generation_id: 9 } }];
  const paths = [];
  const request = async (path) => { paths.push(path); return replies.shift(); };

  const job = await pollJob(5, request, noWait);

  assert.deepEqual(paths, ['/api/jobs/5', '/api/jobs/5']);
  assert.equal(job.result.generation_id, 9);
});

test('polling gives up on a job that never finishes', async () => {
  const request = async () => ({ status: 'queued' });

  await assert.rejects(pollJob(5, request, noWait), (error) => error.code === 'job_unavailable');
});

test('it listens on the jobs stream', () => {
  follow();
  assert.equal(FakeEventSource.last.url, '/api/jobs/5/events');
  assert.equal(FakeEventSource.last.name, 'status');
});

test('it resolves with the last event, and closes so the browser wont reconnect', async () => {
  const followed = follow();
  const source = FakeEventSource.last;

  source.send({ status: 'done', result: { generation_id: 9 } });

  assert.deepEqual(await followed, { status: 'done', result: { generation_id: 9 } });
  assert.equal(source.closed, true);
});

test('a failed job resolves too, since it is an answer and not a lost connection', async () => {
  const followed = follow();

  FakeEventSource.last.send({ status: 'failed', error: 'It went wrong.' });

  assert.equal((await followed).error, 'It went wrong.');
});

test('events before the end go to onProgress, and leave the stream open', async () => {
  const heard = [];
  const followed = follow({ onProgress: (event) => heard.push(event.status) });
  const source = FakeEventSource.last;

  source.send({ status: 'queued' });
  source.send({ status: 'running' });
  assert.equal(source.closed, false);

  source.send({ status: 'done', result: {} });
  await followed;
  assert.deepEqual(heard, ['queued', 'running']);
});

test('a dropped connection keeps waiting, because the browser reconnects', async () => {
  const followed = follow();
  const source = FakeEventSource.last;

  source.readyState = 0;
  source.onerror();
  assert.equal(source.closed, false);

  source.send({ status: 'done', result: {} });
  assert.equal((await followed).status, 'done');
});

test('aborting closes the stream', () => {
  const controller = new AbortController();
  follow({ signal: controller.signal });

  controller.abort();

  assert.equal(FakeEventSource.last.closed, true);
});

test('a connection the browser gave up on rejects', async () => {
  const followed = follow();
  const source = FakeEventSource.last;

  source.readyState = FakeEventSource.CLOSED;
  source.onerror();

  await assert.rejects(followed, (error) => error.code === 'job_unavailable');
  assert.equal(source.closed, true);
});
