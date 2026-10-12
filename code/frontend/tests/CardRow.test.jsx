// @vitest-environment jsdom
//
// The first component test (Lab 3, Step 0b). It proves the Vitest + React Testing Library
// setup works before the study page needs it. CardRow takes plain props and needs no
// login state, so it's the simplest component to prove it on.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import CardRow from '../src/components/CardRow.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const card = { id: 7, deck_id: 3, front: 'la biblioteca', back: 'the library' };
const NOW = Date.parse('2026-10-01T14:00:00Z');

function renderRow(props = {}) {
  return render(
    <ul>
      <CardRow card={card} index={0} onSave={vi.fn()} onDelete={vi.fn()} now={NOW} {...props} />
    </ul>,
  );
}

test('shows the front and back of the card', () => {
  renderRow();

  expect(screen.getByText('la biblioteca')).toBeTruthy();
  expect(screen.getByText('the library')).toBeTruthy();
});

test('clicking Delete asks for confirmation before deleting anything', () => {
  const onDelete = vi.fn();
  renderRow({ onDelete });

  fireEvent.click(screen.getByRole('button', { name: 'Delete card 1' }));

  expect(screen.getByRole('group', { name: 'Confirm deleting card 1' })).toBeTruthy();
  expect(onDelete).not.toHaveBeenCalled();
});

// F4: the schedule badge. CardRow takes `now` so every row on the page agrees.
//
// AI Utilization: ~100% of the tests below
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
// and review by Nurzat Mukhamedali.

test('a review card due in 25 days shows "Review · in 25d"', () => {
  const due = new Date(NOW + 25 * 86_400 * 1000).toISOString();
  renderRow({ card: { ...card, state: 'review', due_at: due } });

  expect(screen.getByText('Review · in 25d').className).toBe('badge badge-blue');
});

test('a new card shows "New"', () => {
  renderRow({ card: { ...card, state: 'new', due_at: null } });

  expect(screen.getByText('New')).toBeTruthy();
});

// ---- F3 (Iteration 3): the AI badge -----------------------------------------------
// AI Utilization: 90% | AI Tools Used: Claude | AI-Assisted Activities: unit test creation
// Human role: checked against F3's acceptance examples and opened the PR, by Osasenaga Von Okunbor.

test('an AI card shows "AI-generated" beside its schedule badge', () => {
  renderRow({ card: { ...card, state: 'new', due_at: null, origin: 'ai' } });

  const ai = screen.getByText('AI-generated');
  expect(ai.className).toBe('badge badge-ai');
  expect(ai.parentElement).toBe(screen.getByText('New').parentElement);
});

test('a manual card, or one with no origin, has no AI badge', () => {
  const { rerender } = renderRow({ card: { ...card, origin: 'manual' } });
  expect(screen.queryByText('AI-generated')).toBeNull();

  rerender(<ul><CardRow card={card} index={0} onSave={vi.fn()} onDelete={vi.fn()} now={NOW} /></ul>);
  expect(screen.queryByText('AI-generated')).toBeNull();
});
