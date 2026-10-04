// @vitest-environment jsdom
//
// One deck and its cards (WS4, Iteration 1). DeckDetailView takes `api` as a prop, so
// these tests pass a fake one instead of mocking fetch (rule 12 in the Iteration 2 plan).
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DeckDetailView } from '../src/pages/DeckDetailPage.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const DECK = { id: 2, name: 'Travel Spanish', description: 'English → Spanish' };
const BEACH = { id: 7, deck_id: 2, front: 'la playa', back: 'the beach' };
const apiError = (code, message) => Object.assign(new Error(message), { code });

function fakeApi(cards = [BEACH]) {
  return {
    getDeck: vi.fn().mockResolvedValue(DECK),
    listCards: vi.fn().mockResolvedValue(cards),
    createCard: vi.fn(async (deckId, body) => ({ id: 8, deck_id: deckId, ...body })),
    updateCard: vi.fn(async (id, body) => ({ ...BEACH, ...body })),
    deleteCard: vi.fn().mockResolvedValue(null),
  };
}

function renderDetail({ api = fakeApi(), startAdding = false } = {}) {
  const onBack = vi.fn();
  render(<DeckDetailView api={api} deckId="2" onBack={onBack} startAdding={startAdding} />);
  return { api, onBack };
}

const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

test('shows the deck, its description, how many cards, and each card', async () => {
  const { api } = renderDetail();

  expect(screen.getByText('Loading your cards…')).toBeTruthy();
  expect(await screen.findByRole('heading', { name: 'Travel Spanish' })).toBeTruthy();
  expect(screen.getByText('English → Spanish')).toBeTruthy();
  expect(screen.getByText('Your deck · 1 card')).toBeTruthy();
  expect(screen.getByText('la playa')).toBeTruthy();
  expect(screen.getByText('the beach')).toBeTruthy();
  expect(api.getDeck).toHaveBeenCalledWith('2');
  expect(api.listCards).toHaveBeenCalledWith('2');
});

test('a deck that does not exist says so', async () => {
  const api = fakeApi();
  api.getDeck.mockRejectedValue(apiError('not_found', 'Deck not found.'));
  renderDetail({ api });

  expect(await screen.findByRole('heading', { name: 'Unable to open deck' })).toBeTruthy();
  expect(screen.getByRole('alert').textContent).toBe('This deck could not be found.');
});

test('any other failure shows the message, and Try again loads again', async () => {
  const api = fakeApi();
  api.listCards.mockRejectedValueOnce(apiError('network_error', "Can't reach the server."));
  renderDetail({ api });

  expect((await screen.findByRole('alert')).textContent).toBe("Can't reach the server.");
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

  expect(await screen.findByText('la playa')).toBeTruthy();
  expect(api.listCards).toHaveBeenCalledTimes(2);
});

test('← All decks goes back', async () => {
  const { onBack } = renderDetail();

  fireEvent.click(screen.getByRole('button', { name: '← All decks' }));

  expect(onBack).toHaveBeenCalledTimes(1);
});

test('an empty deck says so', async () => {
  renderDetail({ api: fakeApi([]) });

  expect(await screen.findByRole('heading', { name: 'This deck is empty' })).toBeTruthy();
  expect(screen.getByText('Your deck · 0 cards')).toBeTruthy();
});

test('+ Add card saves a card, adds it to the list, and keeps the form open for the next', async () => {
  const { api } = renderDetail({ api: fakeApi([]) });

  fireEvent.click(await screen.findByRole('button', { name: '+ Add card' }));
  expect(screen.getByRole('heading', { name: 'What do you want to remember?' })).toBeTruthy();
  type('Front', 'el mapa');
  type('Back', 'the map');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));

  expect(await screen.findByText('Card saved. Add another or cancel to return to your cards.')).toBeTruthy();
  expect(api.createCard).toHaveBeenCalledWith(2, { front: 'el mapa', back: 'the map' });
  expect(screen.getByText('Your deck · 1 card')).toBeTruthy();
  expect(screen.getByLabelText('Front').value).toBe('');

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('heading', { name: 'Add to your collection' })).toBeNull();
});

test('a new deck opens with the composer, and Finish for now goes back', async () => {
  const { onBack } = renderDetail({ api: fakeApi([]), startAdding: true });

  expect(await screen.findByRole('heading', { name: 'What do you want to remember?' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '+ Add card' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Finish for now' }));

  expect(onBack).toHaveBeenCalledTimes(1);
});

test('editing a card saves it and shows the new text', async () => {
  const { api } = renderDetail();

  fireEvent.click(await screen.findByRole('button', { name: 'Edit card 1' }));
  type('Back', 'the beach (f.)');
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(await screen.findByText('the beach (f.)')).toBeTruthy();
  expect(api.updateCard).toHaveBeenCalledWith(7, { front: 'la playa', back: 'the beach (f.)' });
  expect(screen.getByText('Card updated.')).toBeTruthy();
});

test('deleting a card asks first, then removes it', async () => {
  const { api } = renderDetail();

  fireEvent.click(await screen.findByRole('button', { name: 'Delete card 1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete card' }));

  expect(await screen.findByRole('heading', { name: 'This deck is empty' })).toBeTruthy();
  expect(api.deleteCard).toHaveBeenCalledWith(7);
  expect(screen.getByText('Card deleted.')).toBeTruthy();
});
