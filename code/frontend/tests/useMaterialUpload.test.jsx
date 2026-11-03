// @vitest-environment jsdom

import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import {
  MAX_POLL_FAILURES,
  POLL_MS,
  progressMessage,
  useMaterialUpload,
} from '../src/hooks/useMaterialUpload.js';

beforeEach(() => { vi.useFakeTimers(); });

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const FILE = new File(['Cells divide.'], 'notes.txt');
const processing = (extra = {}) => ({ id: 7, status: 'processing', stage: 'queued', ...extra });
const READY = { id: 7, status: 'ready', stage: 'finding_topics', suggested_topics: ['Cells'] };

function setUp({ upload = processing(), polls = [] } = {}) {
  const getMaterial = vi.fn();
  polls.forEach((poll) => {
    if (poll instanceof Error) getMaterial.mockRejectedValueOnce(poll);
    else getMaterial.mockResolvedValueOnce(poll);
  });
  const api = { upload: vi.fn().mockResolvedValue(upload), getMaterial };
  return { api, ...renderHook(() => useMaterialUpload(api)) };
}

const start = (result, file = FILE) => act(() => result.current.upload(file));
const nextPoll = () => act(() => vi.advanceTimersByTimeAsync(POLL_MS));

function setUpFollowing(follow, polls = [READY]) {
  const getMaterial = vi.fn();
  polls.forEach((poll) => getMaterial.mockResolvedValueOnce(poll));
  const api = { upload: vi.fn().mockResolvedValue(processing({ job_id: 3 })), getMaterial };
  return { api, ...renderHook(() => useMaterialUpload(api, follow)) };
}

test('a file with a job follows it, and shows its progress without polling', async () => {
  let options;
  const follow = vi.fn((_id, given) => { options = given; return new Promise(() => {}); });
  const { api, result } = setUpFollowing(follow);
  await start(result);

  expect(follow.mock.calls[0][0]).toBe(3);
  act(() => options.onProgress({ status: 'running', progress: { stage: 'embedding', chunks_done: 4 } }));
  expect(result.current.material).toMatchObject({ stage: 'embedding', chunks_done: 4, id: 7 });

  await nextPoll();
  expect(api.getMaterial).not.toHaveBeenCalled();
  expect(follow).toHaveBeenCalledTimes(1); // progress doesn't restart the stream
});

test('when the job finishes, the document is read for its final state', async () => {
  const { api, result } = setUpFollowing(vi.fn().mockResolvedValue({ status: 'done' }));
  await start(result);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });

  expect(api.getMaterial).toHaveBeenCalledWith(7);
  expect(result.current.material).toEqual(READY);
});

test('polling takes over if the stream cant be used', async () => {
  const follow = vi.fn().mockRejectedValue(new Error('no stream'));
  const stillGoing = processing({ job_id: 3, stage: 'reading' });
  const { api, result } = setUpFollowing(follow, [stillGoing, READY]);
  await start(result);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current.material.stage).toBe('reading');

  await nextPoll();
  expect(api.getMaterial).toHaveBeenCalledTimes(2);
  expect(result.current.material).toEqual(READY);
  expect(result.current.error).toBeNull();
});

test('leaving the page closes the stream', async () => {
  let signal;
  const follow = vi.fn((_id, given) => { signal = given.signal; return new Promise(() => {}); });
  const { result, unmount } = setUpFollowing(follow);
  await start(result);

  unmount();

  expect(signal.aborted).toBe(true);
});

test('an upload gives its document, and shows uploading until the answer comes', async () => {
  let answer;
  const api = {
    upload: vi.fn(() => new Promise((resolve) => { answer = resolve; })),
    getMaterial: vi.fn(),
  };
  const { result } = renderHook(() => useMaterialUpload(api));

  act(() => { result.current.upload(FILE); });
  expect(result.current.uploading).toBe(true);

  await act(async () => { answer(READY); });

  expect(result.current.uploading).toBe(false);
  expect(result.current.material).toEqual(READY);
  expect(api.upload).toHaveBeenCalledWith(FILE);
});

test('a processing document is polled until it is ready, then polling stops', async () => {
  const { api, result } = setUp({ polls: [processing({ stage: 'reading' }), READY] });

  await start(result);
  expect(api.getMaterial).not.toHaveBeenCalled();

  await nextPoll();
  expect(api.getMaterial).toHaveBeenCalledWith(7);
  expect(result.current.material.stage).toBe('reading');

  await nextPoll();
  expect(result.current.material).toEqual(READY);

  await nextPoll();
  expect(api.getMaterial).toHaveBeenCalledTimes(2);
});

test('a file already processed is never polled', async () => {
  const { api, result } = setUp({ upload: READY });

  await start(result);
  await nextPoll();

  expect(api.getMaterial).not.toHaveBeenCalled();
});

test('a failed document stops polling and keeps its message', async () => {
  const failed = { id: 7, status: 'failed', error: 'It failed.' };
  const { api, result } = setUp({ polls: [failed] });

  await start(result);
  await nextPoll();
  await nextPoll();

  expect(result.current.material.error).toBe('It failed.');
  expect(api.getMaterial).toHaveBeenCalledTimes(1);
});

test('an upload that is refused gives its error', async () => {
  const refusal = new Error('That file is empty.');
  const api = { upload: vi.fn().mockRejectedValue(refusal), getMaterial: vi.fn() };
  const { result } = renderHook(() => useMaterialUpload(api));

  await start(result);

  expect(result.current.error).toBe(refusal);
  expect(result.current.uploading).toBe(false);
  expect(result.current.material).toBeNull();
});

test('a failed poll is tried again, and one success forgives it', async () => {
  const { result } = setUp({ polls: [new Error('offline'), READY] });

  await start(result);
  await nextPoll();
  expect(result.current.error).toBeNull();

  await nextPoll();
  expect(result.current.material).toEqual(READY);
  expect(result.current.error).toBeNull();
});

test('polling gives up after repeated failures', async () => {
  const offline = new Error('offline');
  const { api, result } = setUp({ polls: Array(MAX_POLL_FAILURES).fill(offline) });

  await start(result);
  for (let poll = 0; poll < MAX_POLL_FAILURES + 1; poll += 1) await nextPoll();

  expect(result.current.error).toBe(offline);
  expect(api.getMaterial).toHaveBeenCalledTimes(MAX_POLL_FAILURES);
});

test('reset stops polling and forgets the file', async () => {
  const { api, result } = setUp();

  await start(result);
  act(() => { result.current.reset(); });
  await nextPoll();

  expect(result.current.material).toBeNull();
  expect(api.getMaterial).not.toHaveBeenCalled();
});

test('an answer to an old upload is ignored after a new one starts', async () => {
  const answers = [];
  const api = {
    upload: vi.fn(() => new Promise((resolve) => { answers.push(resolve); })),
    getMaterial: vi.fn(),
  };
  const { result } = renderHook(() => useMaterialUpload(api));

  act(() => { result.current.upload(FILE); });
  act(() => { result.current.upload(new File(['ATP'], 'other.txt')); });
  await act(async () => { answers[1]({ ...READY, id: 2 }); });
  await act(async () => { answers[0]({ ...READY, id: 1 }); });

  expect(result.current.material.id).toBe(2);
});

test('polling stops when the page goes away', async () => {
  const { api, result, unmount } = setUp();

  await start(result);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 2));

  expect(api.getMaterial).not.toHaveBeenCalled();
});

test.each([
  [true, null, 'Uploading your file…'],
  [false, processing(), 'Waiting to start…'],
  [false, processing({ stage: 'reading' }), 'Reading your file…'],
  [false, processing({ stage: 'embedding' }), 'Saving your materials…'],
  [false, processing({ stage: 'finding_topics' }), 'Finding topics…'],
  [false, READY, ''],
  [false, null, ''],
])('the progress message for uploading=%s and %j', (uploading, material, message) => {
  expect(progressMessage(uploading, material)).toBe(message);
});
