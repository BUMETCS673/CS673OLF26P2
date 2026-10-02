// @vitest-environment jsdom
//
// F2: the card in a study session. One test per acceptance example under F2 in
// code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the state badge.

import { afterEach, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import StudyCard from '../src/components/study/StudyCard.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const card = { id: 9, front: 'the suitcase', back: 'la maleta', state: 'learning' };

test('not revealed: the front is visible, and the back is not in the DOM', () => {
  render(<StudyCard card={card} revealed={false} />);

  expect(screen.getByText('the suitcase')).toBeTruthy();
  expect(screen.queryByText('la maleta')).toBeNull();
});

test('revealed: both the front and the back are visible', () => {
  render(<StudyCard card={card} revealed />);

  expect(screen.getByText('the suitcase')).toBeTruthy();
  expect(screen.getByText('la maleta')).toBeTruthy();
});

test('a badge names the card state', () => {
  const { rerender } = render(<StudyCard card={card} revealed={false} />);
  expect(screen.getByText('Learning')).toBeTruthy();

  for (const [state, label] of [['new', 'New'], ['relearning', 'Relearning'], ['review', 'Review']]) {
    rerender(<StudyCard card={{ ...card, state }} revealed={false} />);
    expect(screen.getByText(label)).toBeTruthy();
  }
});
