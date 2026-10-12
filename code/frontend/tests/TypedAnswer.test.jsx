// @vitest-environment jsdom
//
// F6 (Iteration 3): the typed-answer box. What C9 in code/plans/ITERATION_3_PLAN.md says
// about TypedAnswer, before and after grading.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F6 in the plan), direction, and review by Nurzat Mukhamedali.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import TypedAnswer from '../src/components/study/TypedAnswer.jsx';

afterEach(cleanup);

const box = () => screen.getByLabelText('Your answer');
const type = (text) => fireEvent.change(box(), { target: { value: text } });

test('before grading: a focused "Your answer" box and a Check button', () => {
  render(<TypedAnswer answer={null} disabled={false} onSubmit={vi.fn()} />);

  expect(box().ownerDocument.activeElement).toBe(box());
  expect(box().value).toBe('');
  expect(screen.getByRole('button', { name: 'Check' })).toBeTruthy();
});

test('the box turns off autocomplete, autocorrect, autocapitalize and spellcheck', () => {
  render(<TypedAnswer answer={null} disabled={false} onSubmit={vi.fn()} />);

  expect(box().getAttribute('autocomplete')).toBe('off');
  expect(box().getAttribute('autocorrect')).toBe('off');
  expect(box().getAttribute('autocapitalize')).toBe('off');
  expect(box().getAttribute('spellcheck')).toBe('false');
});

test('Check calls onSubmit once with the raw text', () => {
  const onSubmit = vi.fn();
  render(<TypedAnswer answer={null} disabled={false} onSubmit={onSubmit} />);

  type('  El Aeropuerto. ');
  fireEvent.click(screen.getByRole('button', { name: 'Check' }));

  expect(onSubmit).toHaveBeenCalledTimes(1);
  expect(onSubmit).toHaveBeenCalledWith('  El Aeropuerto. ');
});

test('Enter in the box submits too', () => {
  const onSubmit = vi.fn();
  render(<TypedAnswer answer={null} disabled={false} onSubmit={onSubmit} />);

  type('el aeropuerto');
  // jsdom doesn't turn Enter into a submit, so submit the form the way the browser would.
  fireEvent.submit(box().form);

  expect(onSubmit).toHaveBeenCalledWith('el aeropuerto');
});

test('disabled: the box and Check are disabled', () => {
  render(<TypedAnswer answer={null} disabled onSubmit={vi.fn()} />);

  expect(box().disabled).toBe(true);
  expect(screen.getByRole('button', { name: 'Check' }).disabled).toBe(true);
});

test('after grading, correct: "Correct" and the typed answer as written; no box', () => {
  render(<TypedAnswer answer={{ typed: 'El Aeropuerto.', verdict: 'correct', suggestedRating: 'good' }}
    disabled={false} onSubmit={vi.fn()} />);

  const verdict = screen.getByText('Correct');
  expect(verdict.classList.contains('typed-verdict')).toBe(true);
  expect(verdict.classList.contains('correct')).toBe(true);
  expect(screen.getByText('You typed: El Aeropuerto.')).toBeTruthy();
  expect(screen.queryByLabelText('Your answer')).toBeNull();
});

test('after grading, incorrect: "Incorrect", in the incorrect style', () => {
  render(<TypedAnswer answer={{ typed: 'el aeropuerta', verdict: 'incorrect', suggestedRating: 'again' }}
    disabled={false} onSubmit={vi.fn()} />);

  expect(screen.getByText('Incorrect').classList.contains('incorrect')).toBe(true);
  expect(screen.getByText('You typed: el aeropuerta')).toBeTruthy();
});

test('after grading a blank answer: says nothing was typed', () => {
  render(<TypedAnswer answer={{ typed: '  ', verdict: 'incorrect', suggestedRating: 'again' }}
    disabled={false} onSubmit={vi.fn()} />);

  expect(screen.getByText('You typed nothing')).toBeTruthy();
});
