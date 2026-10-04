// @vitest-environment jsdom
//
// The form for creating and editing a deck (WS4, Iteration 1).
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: direction and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import DeckForm from '../src/components/DeckForm.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

function renderForm(props = {}) {
  const onSave = props.onSave ?? vi.fn().mockResolvedValue(undefined);
  const onCancel = vi.fn();
  render(<DeckForm onSave={onSave} onCancel={onCancel} {...props} />);
  return { onSave, onCancel };
}

const name = () => screen.getByLabelText('Deck name');
const description = () => screen.getByLabelText(/Description/);
const create = () => fireEvent.click(screen.getByRole('button', { name: 'Create deck' }));

test('a deck needs a name, and spaces alone are not one', () => {
  const { onSave } = renderForm();

  fireEvent.change(name(), { target: { value: '   ' } });
  create();

  expect(screen.getByRole('alert').textContent).toBe('Give your deck a name.');
  expect(name().getAttribute('aria-invalid')).toBe('true');
  expect(onSave).not.toHaveBeenCalled();
});

test('a name over 120 characters is too long', () => {
  const { onSave } = renderForm();

  fireEvent.change(name(), { target: { value: 'a'.repeat(121) } });
  create();

  expect(screen.getByText('Use 120 characters or fewer.')).toBeTruthy();
  expect(onSave).not.toHaveBeenCalled();
});

test('a description over 1,000 characters is too long', () => {
  const { onSave } = renderForm();

  fireEvent.change(name(), { target: { value: 'Travel Spanish' } });
  fireEvent.change(description(), { target: { value: 'a'.repeat(1001) } });
  create();

  expect(screen.getByText('Use 1,000 characters or fewer.')).toBeTruthy();
  expect(onSave).not.toHaveBeenCalled();
});

test('a valid deck is saved trimmed, and the description may be blank', () => {
  const { onSave } = renderForm();

  fireEvent.change(name(), { target: { value: '  Travel Spanish ' } });
  create();

  expect(onSave).toHaveBeenCalledWith({ name: 'Travel Spanish', description: '' });
});

test('editing starts from the deck and says Save changes', () => {
  const { onSave } = renderForm({ initialValue: { name: 'Spanish 101', description: 'Core vocabulary' } });

  expect(name().value).toBe('Spanish 101');
  expect(description().value).toBe('Core vocabulary');
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(onSave).toHaveBeenCalledWith({ name: 'Spanish 101', description: 'Core vocabulary' });
});

test("a failed save shows the server's message, and the form can be used again", async () => {
  renderForm({ onSave: vi.fn().mockRejectedValue(new Error('Could not reach the server.')) });

  fireEvent.change(name(), { target: { value: 'Travel Spanish' } });
  create();

  expect(await screen.findByText('Could not reach the server.')).toBeTruthy();
  // "Saving…" while the save was in flight; back to Create deck once it failed.
  expect(screen.getByRole('button', { name: 'Create deck' })).toBeTruthy();
  expect(name().value).toBe('Travel Spanish');
});

test('Cancel calls onCancel', () => {
  const { onCancel } = renderForm();

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

  expect(onCancel).toHaveBeenCalledTimes(1);
});
