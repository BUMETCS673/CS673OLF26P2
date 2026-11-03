import { afterEach, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import { createMaterialsApi } from '../src/api/materials.js';
import { createAuthenticatedApi } from '../src/api/request.js';

afterEach(() => { vi.restoreAllMocks(); });

const DOCUMENT = { id: 7, filename: 'notes.pdf', status: 'processing', stage: 'queued' };

/** Replaces fetch with one that always gives `status`, and returns the list of its calls. */
function mockFetch(status = 200, body = DOCUMENT) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    calls.push({ url, ...options });
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}

test('upload posts the file as form data, leaving the Content-Type to the browser', async () => {
  const calls = mockFetch(202);
  const api = createAuthenticatedApi(createMaterialsApi, () => {});
  const file = new File(['Cells divide.'], 'notes.txt', { type: 'text/plain' });

  assert.deepEqual(await api.upload(file), DOCUMENT);

  const [call] = calls;
  assert.equal(call.url, '/api/materials');
  assert.equal(call.method, 'POST');
  assert.equal(call.credentials, 'include');
  assert.equal(call.headers, undefined);
  assert.ok(call.body instanceof FormData);
  assert.equal(call.body.get('file').name, 'notes.txt');
});

test('getMaterial reads one document with the session cookie', async () => {
  const calls = mockFetch();
  const api = createAuthenticatedApi(createMaterialsApi, () => {});

  assert.deepEqual(await api.getMaterial(7), DOCUMENT);

  assert.equal(calls[0].url, '/api/materials/7');
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].credentials, 'include');
});

test('an upload error comes back with the field the server named', async () => {
  const error = { code: 'validation_error', message: 'That file is empty.', field: 'file' };
  mockFetch(422, { error });
  const api = createAuthenticatedApi(createMaterialsApi, () => {});

  await assert.rejects(api.upload(new File([''], 'empty.txt')), {
    code: 'validation_error',
    message: 'That file is empty.',
    field: 'file',
  });
});

test('an expired session on upload calls onUnauthorized', async () => {
  mockFetch(401, { error: { code: 'unauthorized', message: 'Sign in.' } });
  const onUnauthorized = vi.fn();
  const api = createAuthenticatedApi(createMaterialsApi, onUnauthorized);

  await assert.rejects(api.upload(new File(['text'], 'notes.txt')));

  assert.equal(onUnauthorized.mock.calls.length, 1);
});

test('a plain JSON request still sends its JSON Content-Type', async () => {
  const calls = mockFetch(201);
  const api = createAuthenticatedApi(
    (request) => ({ send: (body) => request('/api/decks', { method: 'POST', body }) }),
    () => {},
  );

  await api.send({ name: 'Biology' });

  assert.deepEqual(calls[0].headers, { 'Content-Type': 'application/json' });
  assert.equal(calls[0].body, JSON.stringify({ name: 'Biology' }));
});
