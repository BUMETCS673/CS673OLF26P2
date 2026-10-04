// @vitest-environment jsdom
//
// The deck list (WS4, Iteration 1). DeckListView takes `api` as a prop, so these tests
// pass a fake one instead of mocking fetch (rule 12 in the Iteration 2 plan).
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { DeckListView } from '../src/pages/DeckListPage.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const SPANISH = { id: 1, name: 'Spanish 101', description: 'Core vocabulary', card_count: 4 };
const TRAVEL = { id: 2, name: 'Travel Spanish', description: '', card_count: 1 };

function fakeApi(decks = [SPANISH, TRAVEL]) {
  return {
    listDecks: vi.fn().mockResolvedValue(decks),
    createDeck: vi.fn(async (body) => ({ id: 3, card_count: 0, ...body })),
    updateDeck: vi.fn(async (id, body) => ({ ...SPANISH, ...body })),
    deleteDeck: vi.fn().mockResolvedValue(null),
  };
}

function renderList(api = fakeApi()) {
  const onOpenDeck = vi.fn();
  const onDeckCreated = vi.fn();
  render(<DeckListView api={api} onOpenDeck={onOpenDeck} onDeckCreated={onDeckCreated} />);
  return { api, onOpenDeck, onDeckCreated };
}

const deckTile = (name) => screen.getByRole('button', { name }).closest('li');

test('shows a loading message, then every deck with its card count', async () => {
  renderList();

  expect(screen.getByText('Loading your decks…')).toBeTruthy();
  expect(await screen.findByRole('button', { name: 'Spanish 101' })).toBeTruthy();
  expect(within(deckTile('Spanish 101')).getByText('4 cards')).toBeTruthy();
  expect(within(deckTile('Travel Spanish')).getByText('1 card')).toBeTruthy();
  expect(screen.getByText('5 cards in your library')).toBeTruthy();
});

test('a deck without a description gets a friendly default', async () => {
  renderList();

  await screen.findByRole('button', { name: 'Travel Spanish' });

  expect(within(deckTile('Travel Spanish')).getByText('A fresh space for something worth remembering.')).toBeTruthy();
});

test('the deck name and Open deck both open the deck', async () => {
  const { onOpenDeck } = renderList();

  fireEvent.click(await screen.findByRole('button', { name: 'Travel Spanish' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open Spanish 101' }));

  expect(onOpenDeck.mock.calls).toEqual([[2], [1]]);
});

test('a failed load shows the message, and Try again loads again', async () => {
  const api = fakeApi();
  api.listDecks.mockRejectedValueOnce(new Error("Can't reach the server."));
  renderList(api);

  expect((await screen.findByRole('alert')).textContent).toBe("Can't reach the server.");
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

  expect(await screen.findByRole('button', { name: 'Spanish 101' })).toBeTruthy();
  expect(api.listDecks).toHaveBeenCalledTimes(2);
});

test('with no decks, the empty state offers to create the first one', async () => {
  const { api, onDeckCreated } = renderList(fakeApi([]));

  fireEvent.click(await screen.findByRole('button', { name: 'Create your first deck' }));
  fireEvent.change(screen.getByLabelText('Deck name'), { target: { value: 'Travel Spanish' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create deck' }));

  expect(api.createDeck).toHaveBeenCalledWith({ name: 'Travel Spanish', description: '' });
  await vi.waitFor(() => expect(onDeckCreated).toHaveBeenCalledWith(3));
});

test('+ New deck opens the form, and Cancel closes it', async () => {
  renderList();

  fireEvent.click(await screen.findByRole('button', { name: '+ New deck' }));
  expect(screen.getByRole('heading', { name: 'Create a deck' })).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('heading', { name: 'Create a deck' })).toBeNull();
});

test('editing a deck saves it and shows the new name', async () => {
  const { api } = renderList();

  fireEvent.click(await screen.findByRole('button', { name: 'Edit Spanish 101' }));
  fireEvent.change(screen.getByLabelText('Deck name'), { target: { value: 'Spanish 102' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(await screen.findByRole('button', { name: 'Spanish 102' })).toBeTruthy();
  expect(api.updateDeck).toHaveBeenCalledWith(1, { name: 'Spanish 102', description: 'Core vocabulary' });
  expect(screen.getByText('Deck updated.')).toBeTruthy();
});

test('Delete asks first, and Keep deck backs out', async () => {
  const { api } = renderList();

  fireEvent.click(await screen.findByRole('button', { name: 'Delete Travel Spanish' }));
  const confirm = screen.getByRole('group', { name: 'Confirm deleting Travel Spanish' });
  expect(within(confirm).getByText(/all 1 card\?/)).toBeTruthy();

  fireEvent.click(within(confirm).getByRole('button', { name: 'Keep deck' }));

  expect(screen.queryByRole('group', { name: 'Confirm deleting Travel Spanish' })).toBeNull();
  expect(api.deleteDeck).not.toHaveBeenCalled();
});

test('confirming the delete removes the deck and says so', async () => {
  const { api } = renderList();

  fireEvent.click(await screen.findByRole('button', { name: 'Delete Travel Spanish' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete deck' }));

  expect(await screen.findByText('“Travel Spanish” deleted.')).toBeTruthy();
  expect(api.deleteDeck).toHaveBeenCalledWith(2);
  expect(screen.queryByRole('button', { name: 'Travel Spanish' })).toBeNull();
});

test('a failed delete keeps the deck and shows why', async () => {
  const api = fakeApi();
  api.deleteDeck.mockRejectedValue(new Error('Could not delete this deck.'));
  renderList(api);

  fireEvent.click(await screen.findByRole('button', { name: 'Delete Travel Spanish' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete deck' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Could not delete this deck.');
  expect(screen.getByRole('button', { name: 'Travel Spanish' })).toBeTruthy();
});
