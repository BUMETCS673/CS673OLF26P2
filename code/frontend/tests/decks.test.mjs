import test from 'node:test';
import assert from 'node:assert/strict';
import { createDecksApi } from '../src/api/decks.js';
import { createDemoRequest, DEMO_STORAGE_KEY } from '../src/api/decks.demo.js';

function memoryStorage() {
  const items = new Map();
  return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => items.set(key, value) };
}

test('all nine operations use the agreed API paths, methods and bodies', async () => {
  const calls = [];
  const api = createDecksApi(async (...args) => { calls.push(args); });
  await api.listDecks();
  await api.createDeck({ name: 'Spanish' });
  await api.getDeck(3);
  await api.updateDeck(3, { description: 'Vocabulary' });
  await api.deleteDeck(3);
  await api.listCards(3);
  await api.createCard(3, { front: 'hola', back: 'hello' });
  await api.updateCard(9, { back: 'hi' });
  await api.deleteCard(9);
  assert.deepEqual(calls, [
    ['/api/decks'],
    ['/api/decks', { method: 'POST', body: { name: 'Spanish' } }],
    ['/api/decks/3'],
    ['/api/decks/3', { method: 'PATCH', body: { description: 'Vocabulary' } }],
    ['/api/decks/3', { method: 'DELETE' }],
    ['/api/decks/3/cards'],
    ['/api/decks/3/cards', { method: 'POST', body: { front: 'hola', back: 'hello' } }],
    ['/api/cards/9', { method: 'PATCH', body: { back: 'hi' } }],
    ['/api/cards/9', { method: 'DELETE' }],
  ]);
});

test('API adapter preserves server errors and empty delete responses', async () => {
  const expired = Object.assign(new Error('Authentication required.'), { code: 'unauthorized' });
  const api = createDecksApi(async () => { throw expired; });
  await assert.rejects(api.listDecks(), (error) => error === expired);
  assert.equal(await createDecksApi(async () => undefined).deleteCard(1), undefined);
});

test('demo acceptance flow survives a new client and deck deletion removes its cards', async () => {
  const storage = memoryStorage();
  let api = createDecksApi(createDemoRequest(storage));
  assert.deepEqual(await api.listDecks(), []);
  const deck = await api.createDeck({ name: 'Spanish', description: 'Core vocabulary' });
  const first = await api.createCard(deck.id, { front: 'hola', back: 'hello' });
  const second = await api.createCard(deck.id, { front: 'adiós', back: 'goodbye' });
  assert.equal((await api.getDeck(deck.id)).card_count, 2);
  await api.updateCard(first.id, { back: 'hi' });
  await api.deleteCard(second.id);
  await api.updateDeck(deck.id, { name: 'Spanish 101' });
  api = createDecksApi(createDemoRequest(storage));
  assert.equal((await api.listDecks())[0].name, 'Spanish 101');
  assert.equal((await api.getDeck(deck.id)).card_count, 1);
  assert.equal((await api.listCards(deck.id))[0].back, 'hi');
  await api.deleteDeck(deck.id);
  assert.deepEqual(await api.listDecks(), []);
  await assert.rejects(api.getDeck(deck.id), { code: 'not_found' });
  await assert.rejects(api.updateCard(first.id, { front: 'test' }), { code: 'not_found' });
  assert.deepEqual(JSON.parse(storage.getItem(DEMO_STORAGE_KEY)).cards, []);
});

test('demo rejects invalid input without changing stored data', async () => {
  const storage = memoryStorage();
  const api = createDecksApi(createDemoRequest(storage));
  await assert.rejects(api.createDeck({ name: '   ' }), { code: 'validation_error' });
  await assert.rejects(api.createDeck({ name: 'a'.repeat(121) }), { code: 'validation_error' });
  await assert.rejects(api.createDeck({ name: 'Valid', description: 'a'.repeat(1001) }), { code: 'validation_error' });
  const deck = await api.createDeck({ name: 'a'.repeat(120), description: 'a'.repeat(1000) });
  const card = await api.createCard(deck.id, { front: 'a'.repeat(2000), back: 'Answer' });
  await assert.rejects(api.createCard(deck.id, { front: '', back: 'Answer' }), { code: 'validation_error' });
  await assert.rejects(api.updateCard(card.id, { front: 'Changed', back: 'a'.repeat(2001) }), { code: 'validation_error' });
  assert.equal((await api.listCards(deck.id))[0].front, 'a'.repeat(2000));
  assert.equal((await api.getDeck(deck.id)).card_count, 1);
});

test('storage failures are visible and a failed save keeps the previous data', async () => {
  const storage = memoryStorage();
  const api = createDecksApi(createDemoRequest(storage));
  const deck = await api.createDeck({ name: 'Keep me' });
  const broken = createDecksApi(createDemoRequest({ getItem: storage.getItem, setItem() { throw new Error('Quota exceeded'); } }));
  await assert.rejects(broken.updateDeck(deck.id, { name: 'Lost change' }), { code: 'demo_storage_error' });
  assert.equal((await api.getDeck(deck.id)).name, 'Keep me');
  storage.setItem(DEMO_STORAGE_KEY, '{broken');
  await assert.rejects(api.listDecks(), { code: 'demo_storage_error' });
});
