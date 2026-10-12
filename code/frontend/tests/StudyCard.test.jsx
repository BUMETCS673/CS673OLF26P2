// @vitest-environment jsdom
//
// F2: the card in a study session. One test per acceptance example under F2 in
// code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the state badge.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

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

// ---- F3 (Iteration 3): the AI badge -----------------------------------------------
// AI Utilization: 90% | AI Tools Used: Claude | AI-Assisted Activities: unit test creation
// Human role: checked against F3's acceptance examples and opened the PR, by Osasenaga Von Okunbor.

test('an AI card, not revealed, shows "AI-generated" and still hides the back', () => {
  render(<StudyCard card={{ ...card, origin: 'ai' }} revealed={false} />);

  expect(screen.getByText('AI-generated').className).toBe('badge badge-ai');
  expect(screen.getByText('Learning')).toBeTruthy();
  expect(screen.queryByText('la maleta')).toBeNull();
});

test('a manual card has no AI badge', () => {
  render(<StudyCard card={{ ...card, origin: 'manual' }} revealed />);

  expect(screen.queryByText('AI-generated')).toBeNull();
});
