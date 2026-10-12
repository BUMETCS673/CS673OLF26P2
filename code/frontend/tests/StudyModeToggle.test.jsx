// @vitest-environment jsdom
//
// F5 (Iteration 3): the Flashcard / Typed answer toggle. One test per StudyModeToggle row of
// F5's acceptance table in code/plans/ITERATION_3_PLAN.md, plus what C9 says tests can rely on.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F5 in the plan), direction, and review by Nurzat Mukhamedali.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import StudyModeToggle from '../src/components/study/StudyModeToggle.jsx';

afterEach(cleanup);

test('two radios, Flashcard and Typed answer, in a group labelled "Study mode"', () => {
  render(<StudyModeToggle mode="flashcard" onChange={vi.fn()} />);

  const group = screen.getByRole('group', { name: 'Study mode' });
  const radios = screen.getAllByRole('radio');
  expect(radios.map((radio) => radio.closest('label').textContent)).toEqual(['Flashcard', 'Typed answer']);
  for (const radio of radios) expect(group.contains(radio)).toBe(true);
});

test('mode="flashcard": click "Typed answer" calls onChange("typed"), once', () => {
  const onChange = vi.fn();
  render(<StudyModeToggle mode="flashcard" onChange={onChange} />);

  expect(screen.getByRole('radio', { name: 'Flashcard' }).checked).toBe(true);
  fireEvent.click(screen.getByRole('radio', { name: 'Typed answer' }));

  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith('typed');
});

test('mode="typed": render, and "Typed answer" is checked', () => {
  render(<StudyModeToggle mode="typed" onChange={vi.fn()} />);

  expect(screen.getByRole('radio', { name: 'Typed answer' }).checked).toBe(true);
  expect(screen.getByRole('radio', { name: 'Flashcard' }).checked).toBe(false);
});

test('mode="typed": click "Flashcard" calls onChange("flashcard"), once', () => {
  const onChange = vi.fn();
  render(<StudyModeToggle mode="typed" onChange={onChange} />);

  fireEvent.click(screen.getByRole('radio', { name: 'Flashcard' }));

  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith('flashcard');
});
