// @vitest-environment jsdom
//
// F2: the four rating buttons. One test per acceptance example under F2 in
// code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the order and names F1's tests rely on.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import RatingButtons from '../src/components/study/RatingButtons.jsx';

afterEach(cleanup);

// What B3 sends for a new card: 1m, 5m30s, 10m, 4d (Story 1's first row).
const NEW_CARD_INTERVALS = { again: 60, hard: 330, good: 600, easy: 345600 };

const names = () => screen.getAllByRole('button').map((button) => button.getAttribute('aria-label'));

test("with a new card's intervals, the labels read 1m, 6m, 10m, 4d", () => {
  render(<RatingButtons intervals={NEW_CARD_INTERVALS} disabled={false} onRate={vi.fn()} />);

  for (const interval of ['1m', '6m', '10m', '4d']) {
    expect(screen.getByText(interval)).toBeTruthy();
  }
  expect(names()).toEqual(['Again, 1m', 'Hard, 6m', 'Good, 10m', 'Easy, 4d']);
});

test('with no intervals: four buttons with no interval text', () => {
  render(<RatingButtons disabled={false} onRate={vi.fn()} />);

  expect(names()).toEqual(['Again', 'Hard', 'Good', 'Easy']);
  expect(screen.queryByText(/^\d+(m|h|d|mo|y)$/)).toBeNull();
  expect(screen.queryByText('<1m')).toBeNull();
});

test('clicking Hard calls onRate with hard, once', () => {
  const onRate = vi.fn();
  render(<RatingButtons intervals={NEW_CARD_INTERVALS} disabled={false} onRate={onRate} />);

  fireEvent.click(screen.getByRole('button', { name: /^Hard/ }));

  expect(onRate).toHaveBeenCalledTimes(1);
  expect(onRate).toHaveBeenCalledWith('hard');
});

test('disabled: clicking Hard does not call onRate', () => {
  const onRate = vi.fn();
  render(<RatingButtons intervals={NEW_CARD_INTERVALS} disabled onRate={onRate} />);

  for (const button of screen.getAllByRole('button')) expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: /^Hard/ }));

  expect(onRate).not.toHaveBeenCalled();
});

test('each button names its keyboard shortcut, 1 to 4 in order', () => {
  render(<RatingButtons disabled={false} onRate={vi.fn()} />);

  expect(screen.getAllByRole('button').map((button) => button.getAttribute('aria-keyshortcuts')))
    .toEqual(['1', '2', '3', '4']);
});
