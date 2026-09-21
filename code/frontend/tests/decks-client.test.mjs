import test from 'node:test';
import assert from 'node:assert/strict';
import { decksApi } from '../src/api/decks.client.js';

test('WS4 calls WS3 client with one /api prefix, cookies, JSON and empty deletes', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, ...options });
    return options.method === 'DELETE'
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify({ id: 3 }), { status: 200 });
  });
  await decksApi.listDecks();
  await decksApi.createDeck({ name: 'Spanish' });
  await decksApi.getDeck(3);
  await decksApi.updateDeck(3, { name: 'Spanish 101' });
  assert.equal(await decksApi.deleteDeck(3), null);
  await decksApi.listCards(3);
  await decksApi.createCard(3, { front: 'hola', back: 'hello' });
  await decksApi.updateCard(9, { back: 'hi' });
  assert.equal(await decksApi.deleteCard(9), null);
  assert.deepEqual(calls.map(({ url, method }) => [url, method]), [
    ['/api/decks', 'GET'], ['/api/decks', 'POST'], ['/api/decks/3', 'GET'],
    ['/api/decks/3', 'PATCH'], ['/api/decks/3', 'DELETE'],
    ['/api/decks/3/cards', 'GET'], ['/api/decks/3/cards', 'POST'],
    ['/api/cards/9', 'PATCH'], ['/api/cards/9', 'DELETE'],
  ]);
  assert.ok(calls.every((call) => call.credentials === 'include'));
  assert.equal(calls[1].headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[1].body), { name: 'Spanish' });
  assert.deepEqual(JSON.parse(calls[6].body), { front: 'hola', back: 'hello' });
});

test('WS3 validation and auth errors reach WS4 unchanged', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    error: { code: 'validation_error', message: 'name is required', field: 'name' },
  }), { status: 422 }));
  await assert.rejects(decksApi.createDeck({ name: '' }), {
    status: 422, code: 'validation_error', field: 'name', message: 'name is required',
  });
  globalThis.fetch.mock.mockImplementation(async () => new Response(JSON.stringify({
    error: { code: 'unauthorized', message: 'Authentication required.' },
  }), { status: 401 }));
  await assert.rejects(decksApi.listDecks(), { status: 401, code: 'unauthorized' });
});
