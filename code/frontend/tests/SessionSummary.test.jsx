// @vitest-environment jsdom
//
// F3: the session summary. One test per acceptance example under F3 in
// code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the Study more button F1's tests rely on
// and the edge cases the session reducer can produce.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F3 in the plan), direction, and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import SessionSummary from '../src/components/study/SessionSummary.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

// A fixed clock, so "More cards in 25m" doesn't depend on when the test runs.
const NOW = Date.parse('2026-10-01T14:00:00Z');
const ZERO = { again: 0, hard: 0, good: 0, easy: 0 };

function renderSummary(props = {}) {
  return render(
    <SessionSummary counts={ZERO} nextLearningDue={null} now={NOW}
      onStudyMore={vi.fn()} onExit={vi.fn()} {...props} />,
  );
}

const studyMore = () => screen.queryByRole('button', { name: 'Study more' });

test('with answers and no next due time: Session complete, 3 cards, and no Study more', () => {
  renderSummary({ counts: { again: 1, hard: 0, good: 2, easy: 0 } });

  expect(screen.getByRole('heading', { name: 'Session complete' })).toBeTruthy();
  expect(screen.getByText('3 cards')).toBeTruthy();
  expect(screen.getAllByRole('listitem').map((item) => item.textContent))
    .toEqual(['Again1', 'Hard0', 'Good2', 'Easy0']);
  expect(studyMore()).toBeNull();
});

test('a next due time 25 minutes after now: More cards in 25m, and Study more calls onStudyMore', () => {
  const onStudyMore = vi.fn();
  renderSummary({
    counts: { again: 0, hard: 0, good: 1, easy: 0 },
    nextLearningDue: '2026-10-01T14:25:00Z',
    onStudyMore,
  });

  expect(screen.getByText('More cards in 25m')).toBeTruthy();
  fireEvent.click(studyMore());

  expect(onStudyMore).toHaveBeenCalledTimes(1);
});

test('every count zero: Nothing to study right now', () => {
  renderSummary();

  expect(screen.getByRole('heading', { name: 'Nothing to study right now' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Session complete' })).toBeNull();
  expect(studyMore()).toBeNull();
});

test('one card answered says 1 card, not 1 cards', () => {
  renderSummary({ counts: { again: 0, hard: 0, good: 0, easy: 1 } });

  expect(screen.getByText('1 card')).toBeTruthy();
});

test('a next due time already past shows <1m, never a negative wait', () => {
  renderSummary({
    counts: { again: 0, hard: 0, good: 1, easy: 0 },
    nextLearningDue: '2026-10-01T13:59:00Z',
  });

  expect(screen.getByText('More cards in <1m')).toBeTruthy();
});

// initSession finishes straight away when the only due cards are learning cards beyond
// the 20-minute learn-ahead window: nothing answered, but a next due time.
test('nothing answered but a learning card coming: the empty state, with Study more', () => {
  renderSummary({ nextLearningDue: '2026-10-01T14:25:00Z' });

  expect(screen.getByRole('heading', { name: 'Nothing to study right now' })).toBeTruthy();
  expect(screen.getByText('More cards in 25m')).toBeTruthy();
  expect(studyMore()).toBeTruthy();
});

test('clicking Back to deck calls onExit', () => {
  const onExit = vi.fn();
  renderSummary({ counts: { again: 0, hard: 0, good: 1, easy: 0 }, onExit });

  fireEvent.click(screen.getByRole('button', { name: 'Back to deck' }));

  expect(onExit).toHaveBeenCalledTimes(1);
});
