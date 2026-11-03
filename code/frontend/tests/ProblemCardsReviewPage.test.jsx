// @vitest-environment jsdom

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createProblemCardsApi } from '../src/api/problemCards.js';
import { ProblemCardsReviewView } from '../src/pages/ProblemCardsReviewPage.jsx';

afterEach(cleanup);

const REVIEW = {
  id: 3,
  deck_id: 2,
  status: 'pending',
  shared_cause: 'These cards are all about cellular respiration.',
  recommendations: [{
    card_id: 7,
    front: 'What does it do?',
    back: 'Makes energy',
    lapses: 5,
    options: [
      {
        kind: 'rewrite',
        reason: 'The question is vague.',
        cards: [{ front: 'Which molecule?', back: 'ATP' }],
      },
      {
        kind: 'contrast',
        reason: 'It is confused with another card.',
        cards: [{ front: 'Which organelle?', back: 'Mitochondria' }],
      },
    ],
  }],
};
const apiError = (code, message) => Object.assign(new Error(message), { code });
const applied = (kind) => ({
  review: { decisions: [{ card_id: 7, kind, new_card_ids: kind === 'rewrite' ? [8] : [] }] },
  cards: kind === 'rewrite' ? [{ id: 8, front: 'Which molecule?', back: 'ATP' }] : [],
});

function fakeApi(overrides = {}) {
  return {
    getDeckReview: vi.fn().mockResolvedValue({ review: REVIEW }),
    submitDecisions: vi.fn().mockResolvedValue(applied('rewrite')),
    ...overrides,
  };
}

async function open(api = fakeApi(), props = {}) {
  render(<ProblemCardsReviewView api={api} deckId="2" onExit={vi.fn()} {...props} />);
  await screen.findByRole('button', { name: 'Apply my choices' });
  return api;
}

const radio = (name) => screen.getByRole('radio', { name });
const applyButton = () => screen.getByRole('button', { name: 'Apply my choices' });

test('the API calls the three routes', () => {
  const request = vi.fn();
  const api = createProblemCardsApi(request);

  api.getSuggestions();
  api.getDeckReview(2);
  api.submitDecisions(3, [{ card_id: 7, option: 0 }]);

  expect(request.mock.calls).toEqual([
    ['/api/problem-cards'],
    ['/api/decks/2/problem-card-review'],
    ['/api/problem-card-reviews/3/decisions', {
      method: 'POST', body: { decisions: [{ card_id: 7, option: 0 }] },
    }],
  ]);
});

test('it opens straight on the recommendations, with the evidence and the shared cause', async () => {
  await open();

  expect(screen.getByText('These cards are all about cellular respiration.')).toBeTruthy();
  expect(screen.getByText('Forgotten 5 times')).toBeTruthy();
  expect(screen.getByText('The question is vague.')).toBeTruthy();
  expect(screen.getByText('New: Which molecule? → ATP')).toBeTruthy();
});

test('it says what each option does to the card', async () => {
  await open();

  expect(screen.getByText('This replaces your card and starts over.')).toBeTruthy();
  expect(screen.getByText('Your card stays. New cards are added.')).toBeTruthy();
});

test('a skipped accuracy check says so', async () => {
  await open(fakeApi({
    getDeckReview: vi.fn().mockResolvedValue({ review: { ...REVIEW, verification: 'skipped' } }),
  }));

  expect(screen.getByText(/accuracy check didn't run/)).toBeTruthy();
});

test('a passed accuracy check shows no warning', async () => {
  await open(fakeApi({
    getDeckReview: vi.fn().mockResolvedValue({ review: { ...REVIEW, verification: 'passed' } }),
  }));

  expect(screen.queryByText(/accuracy check didn't run/)).toBeNull();
});

test('keeping is the default', async () => {
  await open();

  expect(radio(/Keep it as it is/).checked).toBe(true);
});

test('with nothing pending it says so', async () => {
  render(<ProblemCardsReviewView api={fakeApi({ getDeckReview: vi.fn().mockResolvedValue({ review: null }) })}
    deckId="2" onExit={vi.fn()} />);

  expect(await screen.findByText('There are no suggestions for this deck right now.')).toBeTruthy();
});

test('applying sends the choice, shows what changed and refreshes the store', async () => {
  const onApplied = vi.fn();
  const api = await open(fakeApi(), { onApplied });

  fireEvent.click(radio(/Rewrite this card/));
  fireEvent.click(applyButton());

  expect((await screen.findByRole('status')).textContent).toContain('1 card improved, 0 removed, 0 kept');
  expect(screen.getByText('1 new card added to your deck.')).toBeTruthy();
  expect(api.submitDecisions).toHaveBeenCalledWith(3, [{ card_id: 7, option: 0 }]);
  expect(onApplied).toHaveBeenCalled();
});

test('a card left alone is sent as kept, and the pause is explained', async () => {
  const api = await open(fakeApi({ submitDecisions: vi.fn().mockResolvedValue(applied(null)) }));

  fireEvent.click(applyButton());

  expect(await screen.findByText('No new suggestions for this deck for 7 days.')).toBeTruthy();
  expect(api.submitDecisions).toHaveBeenCalledWith(3, [{ card_id: 7, option: null }]);
});

test('going back to keeping a card clears the earlier choice', async () => {
  const api = await open();

  fireEvent.click(radio(/Rewrite this card/));
  fireEvent.click(radio(/Keep it as it is/));
  fireEvent.click(applyButton());

  await waitFor(() => expect(api.submitDecisions).toHaveBeenCalledWith(3, [{ card_id: 7, option: null }]));
});

test('removing a card asks first', async () => {
  const api = await open(fakeApi({ submitDecisions: vi.fn().mockResolvedValue(applied('remove')) }));

  fireEvent.click(radio(/Remove this card/));
  fireEvent.click(applyButton());

  expect(api.submitDecisions).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Delete and apply' }));

  expect((await screen.findByRole('status')).textContent).toContain('0 cards improved, 1 removed, 0 kept');
  expect(api.submitDecisions).toHaveBeenCalledWith(3, [{ card_id: 7, option: 'remove' }]);
});

test('going back from the confirmation sends nothing', async () => {
  const api = await open();

  fireEvent.click(radio(/Remove this card/));
  fireEvent.click(applyButton());
  fireEvent.click(screen.getByRole('button', { name: 'Go back' }));

  expect(applyButton()).toBeTruthy();
  expect(api.submitDecisions).not.toHaveBeenCalled();
});

test('a double click applies once', async () => {
  const api = await open();

  const button = applyButton();
  fireEvent.click(button);
  fireEvent.click(button);

  await screen.findByRole('status');
  expect(api.submitDecisions).toHaveBeenCalledTimes(1);
});

test('a failed apply keeps the choices on screen', async () => {
  const api = fakeApi({ submitDecisions: vi.fn().mockRejectedValue(apiError('conflict', 'Already completed.')) });
  await open(api);

  fireEvent.click(radio(/Rewrite this card/));
  fireEvent.click(applyButton());

  expect((await screen.findByRole('alert')).textContent).toBe('Already completed.');
  expect(radio(/Rewrite this card/).checked).toBe(true);
});

test('a 401 shows no error, because the adapter signs out', async () => {
  await open(fakeApi({ submitDecisions: vi.fn().mockRejectedValue(apiError('unauthorized', 'Sign in.')) }));

  fireEvent.click(applyButton());

  await waitFor(() => expect(applyButton().disabled).toBe(false));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('a failed load shows the error', async () => {
  render(<ProblemCardsReviewView api={fakeApi({ getDeckReview: vi.fn().mockRejectedValue(apiError('not_found', 'Deck not found')) })}
    deckId="2" onExit={vi.fn()} />);

  expect(await screen.findByRole('alert')).toBeTruthy();
});
