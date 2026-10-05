// @vitest-environment jsdom
//
// F4: the Study now button and the due-count badge on one deck's page. One test per
// DeckDetailView acceptance example under F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md.
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

function renderDetail({ deck = DECK, cards = [BEACH] } = {}) {
  const api = {
    getDeck: vi.fn().mockResolvedValue(deck),
    listCards: vi.fn().mockResolvedValue(cards),
  };
  const onStudy = vi.fn();
  const { container } = render(<DeckDetailView api={api} deckId="2" onBack={vi.fn()} onStudy={onStudy} />);
  return { onStudy, container };
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
