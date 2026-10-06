// @vitest-environment jsdom
//
// F4: the Study now button and the due-count badge on one deck's page. One test per
// DeckDetailView acceptance example under F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md,
// plus the badge refreshing after a card is added or deleted (review on #56).
// The Iteration 1 behaviors stay covered by DeckDetailPage.test.jsx.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F4 in the plan), direction, and review by Nurzat Mukhamedali.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DeckDetailView } from '../src/pages/DeckDetailPage.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const DECK = { id: 2, name: 'Travel Spanish', description: 'English → Spanish' };
const DUE_NINE = { learning: 3, review: 3, new: 3 };
const BEACH = { id: 7, deck_id: 2, front: 'la playa', back: 'the beach', state: 'new', due_at: null };

const NO_COUNTS = { learning: 0, review: 0, new: 0 };

function renderDetail({ deck = DECK, cards = [BEACH], api: overrides = {} } = {}) {
  const api = {
    getDeck: vi.fn().mockResolvedValue(deck),
    listCards: vi.fn().mockResolvedValue(cards),
    createCard: vi.fn(async (deckId, body) => ({ id: 8, deck_id: deckId, state: 'new', due_at: null, ...body })),
    deleteCard: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
  const onStudy = vi.fn();
  const { container } = render(<DeckDetailView api={api} deckId="2" onBack={vi.fn()} onStudy={onStudy} />);
  return { api, onStudy, container };
}

function addCard(front, back) {
  fireEvent.change(screen.getByLabelText('Front'), { target: { value: front } });
  fireEvent.change(screen.getByLabelText('Back'), { target: { value: back } });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
}

test('a deck with cards and nine due shows "Study now · 9", which calls onStudy', async () => {
  const { onStudy } = renderDetail({ deck: { ...DECK, due_counts: DUE_NINE } });

  fireEvent.click(await screen.findByRole('button', { name: 'Study now · 9' }));

  expect(onStudy).toHaveBeenCalledTimes(1);
  expect(screen.getByText('6 due · 3 new').className).toContain('badge-gold');
});

test('a deck with no cards has no Study button', async () => {
  renderDetail({ deck: { ...DECK, due_counts: { learning: 0, review: 0, new: 0 } }, cards: [] });

  expect(await screen.findByRole('heading', { name: 'This deck is empty' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Study now/ })).toBeNull();
});

test('a deck with cards but no due_counts shows "Study now" and no counts badge', async () => {
  const { container } = renderDetail();

  expect(await screen.findByRole('button', { name: 'Study now' })).toBeTruthy();
  expect(container.querySelector('.badge-gold')).toBeNull();
});

test('each card shows where it stands', async () => {
  renderDetail();

  expect(await screen.findByText('New')).toBeTruthy();
});

test('adding a card to a new deck changes the badge to "1 new"', async () => {
  const getDeck = vi.fn()
    .mockResolvedValueOnce({ ...DECK, due_counts: NO_COUNTS })
    .mockResolvedValueOnce({ ...DECK, due_counts: { ...NO_COUNTS, new: 1 } });
  renderDetail({ cards: [], api: { getDeck } });

  expect(await screen.findByText('All caught up')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '+ Add card' }));
  addCard('el mapa', 'the map');

  expect(await screen.findByText('1 new')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Study now · 1' })).toBeTruthy();
  expect(getDeck).toHaveBeenCalledTimes(2);
});

test('deleting the last card drops its count from the badge', async () => {
  const getDeck = vi.fn()
    .mockResolvedValueOnce({ ...DECK, due_counts: { ...NO_COUNTS, new: 1 } })
    .mockResolvedValueOnce({ ...DECK, due_counts: NO_COUNTS });
  renderDetail({ api: { getDeck } });

  expect(await screen.findByText('1 new')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Delete card 1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete card' }));

  expect(await screen.findByText('All caught up')).toBeTruthy();
  expect(screen.queryByText('1 new')).toBeNull();
  expect(screen.queryByRole('button', { name: /Study now/ })).toBeNull();
});

test('if refreshing the deck fails, the card is still added and the old counts stay', async () => {
  const getDeck = vi.fn()
    .mockResolvedValueOnce({ ...DECK, due_counts: NO_COUNTS })
    .mockRejectedValueOnce(Object.assign(new Error("Can't reach the server."), { code: 'network_error' }));
  renderDetail({ cards: [], api: { getDeck } });

  fireEvent.click(await screen.findByRole('button', { name: '+ Add card' }));
  addCard('el mapa', 'the map');

  expect(await screen.findByText('Your deck · 1 card')).toBeTruthy();
  await vi.waitFor(() => expect(getDeck).toHaveBeenCalledTimes(2));
  expect(screen.getByText('All caught up')).toBeTruthy();
});
