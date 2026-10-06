// @vitest-environment jsdom
//
// F4: due counts and the Study button on the deck list. The acceptance example for
// DeckListView under F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the decks that
// don't carry due_counts yet (rule 10). The Iteration 1 behaviors stay covered by
// DeckListPage.test.jsx.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F4 in the plan), direction, and review by Nurzat Mukhamedali.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { DeckListView } from '../src/pages/DeckListPage.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const SPANISH = {
  id: 1, name: 'Spanish 101', description: '', card_count: 4,
  due_counts: { learning: 0, review: 0, new: 4 },
};
const TRAVEL = {
  id: 2, name: 'Travel Spanish', description: '', card_count: 11,
  due_counts: { learning: 3, review: 3, new: 3 },
};

function renderList(decks) {
  const api = { listDecks: vi.fn().mockResolvedValue(decks) };
  const onStudyDeck = vi.fn();
  render(<DeckListView api={api} onOpenDeck={vi.fn()} onStudyDeck={onStudyDeck} />);
  return { onStudyDeck };
}

const deckTile = (name) => screen.getByRole('button', { name: `Open ${name}` }).closest('li');

test('a deck with four new cards shows "4 new", and Study calls onStudyDeck with its id', async () => {
  const { onStudyDeck } = renderList([SPANISH, TRAVEL]);
  await screen.findByRole('button', { name: 'Open Spanish 101' });

  expect(within(deckTile('Spanish 101')).getByText('4 new').className).toBe('badge badge-gold');
  expect(within(deckTile('Travel Spanish')).getByText('6 due · 3 new')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Study Spanish 101' }));

  expect(onStudyDeck).toHaveBeenCalledWith(1);
});

test('a deck without due_counts shows no counts badge', async () => {
  renderList([{ ...SPANISH, due_counts: undefined }]);
  await screen.findByRole('button', { name: 'Open Spanish 101' });

  expect(deckTile('Spanish 101').querySelector('.badge-gold')).toBeNull();
  expect(within(deckTile('Spanish 101')).getByText('4 cards')).toBeTruthy();
});
