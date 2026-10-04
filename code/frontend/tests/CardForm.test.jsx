// @vitest-environment jsdom
//
// The form for adding and editing a card (WS4, Iteration 1).
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CardForm from '../src/components/CardForm.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

function renderForm(props = {}) {
  const onSave = props.onSave ?? vi.fn().mockResolvedValue(undefined);
  const onCancel = vi.fn();
  render(<CardForm onSave={onSave} onCancel={onCancel} {...props} />);
  return { onSave, onCancel };
}

const field = (name) => screen.getByLabelText(name);
const type = (name, value) => fireEvent.change(field(name), { target: { value } });

test('a blank front and back are both reported, and nothing is saved', () => {
  const { onSave } = renderForm();

  type('Back', '   ');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));

  expect(screen.getByText('The front of your card cannot be blank.')).toBeTruthy();
  expect(screen.getByText('The back of your card cannot be blank.')).toBeTruthy();
  expect(field('Front').getAttribute('aria-invalid')).toBe('true');
  expect(onSave).not.toHaveBeenCalled();
});

test('more than 2,000 characters is too long', () => {
  const { onSave } = renderForm();

  type('Front', 'a'.repeat(2001));
  type('Back', 'b');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));

  expect(screen.getByText('Use 2,000 characters or fewer.')).toBeTruthy();
  expect(onSave).not.toHaveBeenCalled();
});

test('the character count follows the text', () => {
  renderForm();

  type('Front', 'hola');

  expect(screen.getByText('4 / 2,000 characters')).toBeTruthy();
});

test('a new card is saved trimmed, then the form clears for the next one', async () => {
  const { onSave } = renderForm();

  type('Front', '  la playa ');
  type('Back', ' the beach  ');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));

  expect(onSave).toHaveBeenCalledWith({ front: 'la playa', back: 'the beach' });
  await waitFor(() => expect(field('Front').value).toBe(''));
  expect(field('Back').value).toBe('');
});

test('editing starts from the card, says Save changes, and keeps the text after saving', async () => {
  const { onSave } = renderForm({ initialValue: { front: 'la playa', back: 'the beach' } });

  expect(field('Front').value).toBe('la playa');
  type('Back', 'the beach (f.)');
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(onSave).toHaveBeenCalledWith({ front: 'la playa', back: 'the beach (f.)' });
  // "Saving…" while the save is in flight, then back.
  expect(await screen.findByRole('button', { name: 'Save changes' })).toBeTruthy();
  expect(field('Back').value).toBe('the beach (f.)');
});

test("a failed save shows the server's message and keeps what was typed", async () => {
  renderForm({ onSave: vi.fn().mockRejectedValue(new Error('Deck not found.')) });

  type('Front', 'la playa');
  type('Back', 'the beach');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));

  expect((await screen.findByText('Deck not found.')).getAttribute('role')).toBe('alert');
  expect(field('Front').value).toBe('la playa');
});

test('Cancel calls onCancel, with its label configurable', () => {
  const { onCancel } = renderForm({ cancelLabel: 'Done' });

  fireEvent.click(screen.getByRole('button', { name: 'Done' }));

  expect(onCancel).toHaveBeenCalledTimes(1);
});
