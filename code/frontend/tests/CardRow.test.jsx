// @vitest-environment jsdom
//
// The first component test (Lab 3, Step 0b). It proves the Vitest + React Testing Library
// setup works before the study page needs it. CardRow takes plain props and needs no
// login state, so it's the simplest component to prove it on.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import CardRow from '../src/components/CardRow.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const card = { id: 7, deck_id: 3, front: 'la biblioteca', back: 'the library' };

function renderRow(props = {}) {
  return render(
    <ul>
      <CardRow card={card} index={0} onSave={vi.fn()} onDelete={vi.fn()} {...props} />
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
