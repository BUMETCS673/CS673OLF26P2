// @vitest-environment jsdom
//
// F2's tests: one per acceptance example under F2 in code/plans/ITERATION_3_PLAN.md, plus
// the singular and plural wording and each decided card's label.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation (from the plan's acceptance examples)
// Human role: plan review, code review, and CI verification by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import CandidateList from '../src/components/generate/CandidateList.jsx';

afterEach(cleanup);

function generationWith(statuses, requested = statuses.length) {
  return {
    id: 7, deck_id: 2, mode: 'prompt', requested_count: requested, model: 'fake',
    created_at: '2026-10-09T14:00:00Z',
    cards: statuses.map((status, index) => ({
      index, front: `Sample question ${index + 1}`, back: `Sample answer ${index + 1}`, status,
    })),
  };
}

function renderList(generation, props = {}) {
  const callbacks = {
    onAccept: vi.fn(), onReject: vi.fn(), onGenerateMore: vi.fn(), onBackToDeck: vi.fn(),
  };
  render(<CandidateList generation={generation} busy={false} error={null} {...callbacks} {...props} />);
  return callbacks;
}

const button = (name) => screen.getByRole('button', { name });
const noButton = (name) => expect(screen.queryByRole('button', { name })).toBeNull();

test('three pending cards show their text, the count, and both bulk buttons', () => {
  renderList(generationWith(['pending', 'pending', 'pending']));

  for (const n of [1, 2, 3]) {
    expect(screen.getByText(`Sample question ${n}`)).toBeTruthy();
    expect(screen.getByText(`Sample answer ${n}`)).toBeTruthy();
    expect(button(`Accept suggestion ${n}`)).toBeTruthy();
    expect(button(`Reject suggestion ${n}`)).toBeTruthy();
  }
  expect(screen.getByRole('heading', { name: '3 suggestions' })).toBeTruthy();
  expect(button('Accept all')).toBeTruthy();
  expect(button('Reject all')).toBeTruthy();
  noButton('Back to deck');
});

test('one card is "1 suggestion"', () => {
  renderList(generationWith(['pending']));

  expect(screen.getByRole('heading', { name: '1 suggestion' })).toBeTruthy();
});

test('accepting or rejecting one card sends its index', () => {
  const { onAccept, onReject } = renderList(generationWith(['pending', 'pending', 'pending']));

  fireEvent.click(button('Accept suggestion 2'));
  fireEvent.click(button('Reject suggestion 3'));

  expect(onAccept).toHaveBeenCalledExactlyOnceWith([1]);
  expect(onReject).toHaveBeenCalledExactlyOnceWith([2]);
});

test('Accept all and Reject all send every pending index, in order', () => {
  const { onAccept, onReject } = renderList(generationWith(['accepted', 'pending', 'pending']));

  fireEvent.click(button('Accept all'));
  fireEvent.click(button('Reject all'));

  expect(onAccept).toHaveBeenCalledExactlyOnceWith([1, 2]);
  expect(onReject).toHaveBeenCalledExactlyOnceWith([1, 2]);
});

test('decided cards show their outcome and lose their buttons', () => {
  renderList(generationWith(['accepted', 'rejected', 'pending']));

  expect(screen.getByText('Added to deck')).toBeTruthy();
  expect(screen.getByText('Rejected')).toBeTruthy();
  noButton('Accept suggestion 1');
  noButton('Reject suggestion 2');
  expect(button('Accept suggestion 3')).toBeTruthy();
});

test('fewer cards than asked for says so', () => {
  renderList(generationWith(Array(8).fill('pending'), 10));

  expect(screen.getByText('Gemini returned 8 of the 10 you asked for.')).toBeTruthy();
});

test('a full batch has no shortfall note', () => {
  renderList(generationWith(['pending', 'pending']));

  expect(screen.queryByText(/Gemini returned/)).toBeNull();
});

test('no cards offers another try', () => {
  const { onGenerateMore } = renderList(generationWith([], 10));

  expect(screen.getByText("Gemini couldn't write cards from that. Try a different prompt or file."))
    .toBeTruthy();
  fireEvent.click(button('Generate more'));
  expect(onGenerateMore).toHaveBeenCalledOnce();
  noButton('Accept all');
});

test('with nothing pending it counts what was added and offers the way out', () => {
  renderList(generationWith(['accepted', 'rejected', 'accepted']));

  expect(screen.getByText('2 cards added')).toBeTruthy();
  expect(button('Back to deck')).toBeTruthy();
  expect(button('Generate more')).toBeTruthy();
  noButton('Accept all');
  noButton('Reject all');
});

test('the summary says "1 card added" and "No cards added"', () => {
  renderList(generationWith(['accepted', 'rejected']));
  expect(screen.getByText('1 card added')).toBeTruthy();
  cleanup();

  renderList(generationWith(['rejected', 'rejected']));
  expect(screen.getByText('No cards added')).toBeTruthy();
});

test('Back to deck and Generate more call their callbacks', () => {
  const { onBackToDeck, onGenerateMore } = renderList(generationWith(['accepted', 'rejected']));

  fireEvent.click(button('Back to deck'));
  expect(onBackToDeck).toHaveBeenCalledOnce();
  fireEvent.click(button('Generate more'));
  expect(onGenerateMore).toHaveBeenCalledOnce();
});

test('while busy every button is disabled', () => {
  const { onAccept } = renderList(generationWith(['pending', 'pending']), { busy: true });

  for (const b of screen.getAllByRole('button')) expect(b.disabled).toBe(true);
  fireEvent.click(button('Accept all'));
  expect(onAccept).not.toHaveBeenCalled();
});

test('while busy the end buttons are disabled too', () => {
  renderList(generationWith(['accepted']), { busy: true });

  expect(button('Back to deck').disabled).toBe(true);
  expect(button('Generate more').disabled).toBe(true);
});

test('an error shows its message in an alert', () => {
  const error = { code: 'not_found', message: 'Generation not found.', status: 404 };

  renderList(generationWith(['pending']), { error });

  expect(screen.getByRole('alert').textContent).toBe('Generation not found.');
});
