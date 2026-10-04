// @vitest-environment jsdom
//
// F1: the study page. One test per acceptance example under F1 in
// code/plans/FINALIZE_ITERATION_2_PLAN.md, plus the keyboard and error cases around them.
// StudyView takes a fake `api` and a fixed clock (rule 12), so nothing here mocks fetch.
// The tests only rely on what "The study components" table promises about StudyCard,
// RatingButtons and SessionSummary, so they pass with the 0b stubs and with F2 and F3.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F1 in the plan), direction, and review by Duc Anh Nguyen.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { StudyView } from '../src/pages/StudyPage.jsx';

// We import Vitest's functions rather than turning on its globals, so React Testing
// Library can't find afterEach to clean up on its own.
afterEach(cleanup);

const NOW = Date.parse('2026-10-01T14:00:00Z');
const MINUTE = 60 * 1000;
const DAY = 24 * 60 * MINUTE;
const iso = (ms) => new Date(ms).toISOString();

// B1's Travel Spanish cards make the fixtures.
const card = (id, front, back, state, dueAt = null) =>
  ({ id, deck_id: 2, front, back, state, due_at: dueAt === null ? null : iso(dueAt) });
const AIRPORT = card(1, 'the airport', 'el aeropuerto', 'review', NOW - 4 * DAY);
const SONG = card(2, 'the song', 'la canción', 'new');
const DECK = { id: 2, name: 'Travel Spanish' };

const due = ({ learning = [], review = [], fresh = [] } = {}) => ({ learning, review, new: fresh });
/** What the server sends back after a rating that leaves the card in review. */
const reviewed = (c) => ({ ...c, state: 'review', due_at: iso(NOW + 3 * DAY) });
const apiError = (code, message = 'Something went wrong') => Object.assign(new Error(message), { code });

function fakeApi({ dueCards = due({ review: [AIRPORT], fresh: [SONG] }), reviewCard } = {}) {
  return {
    getDeck: vi.fn().mockResolvedValue(DECK),
    getDueCards: vi.fn().mockResolvedValue(dueCards),
    reviewCard: reviewCard ?? vi.fn(async (id) => reviewed(id === AIRPORT.id ? AIRPORT : SONG)),
  };
}

function renderView(api = fakeApi(), onExit = vi.fn()) {
  render(<StudyView api={api} deckId="2" onExit={onExit} now={() => NOW} />);
  return { api, onExit };
}

const ratingButton = (name) => screen.queryByRole('button', { name: new RegExp(`^${name}`) });
const showAnswer = () => fireEvent.click(screen.getByRole('button', { name: 'Show answer' }));
const summaryText = () =>
  screen.getByRole('heading', { name: 'Session complete' }).closest('.session-summary').textContent;
// The page listens on window. A key pressed on the page bubbles up to it, the same as a
// real key press with nothing focused.
const press = (key) => fireEvent.keyDown(screen.getByRole('main'), { key });

test('the first card shows its front, not its back, and no rating buttons', async () => {
  renderView();

  expect(await screen.findByText('the airport')).toBeTruthy();
  expect(screen.queryByText('el aeropuerto')).toBeNull();
  expect(ratingButton('Good')).toBeNull();
  expect(screen.getByRole('heading', { name: 'Travel Spanish' })).toBeTruthy();
  expect(screen.getByText('2 cards left')).toBeTruthy();
});

test('Show answer reveals the back and the four rating buttons', async () => {
  renderView();
  await screen.findByText('the airport');

  showAnswer();

  expect(screen.getByText('el aeropuerto')).toBeTruthy();
  for (const name of ['Again', 'Hard', 'Good', 'Easy']) expect(ratingButton(name)).toBeTruthy();
});

test('Space reveals the answer too', async () => {
  renderView();
  await screen.findByText('the airport');

  press(' ');

  expect(screen.getByText('el aeropuerto')).toBeTruthy();
});

test('1-4 do nothing before the answer is showing', async () => {
  const { api } = renderView();
  await screen.findByText('the airport');

  press('3');

  expect(api.reviewCard).not.toHaveBeenCalled();
});

test('Good saves the rating once and shows the next card', async () => {
  const { api } = renderView();
  await screen.findByText('the airport');
  showAnswer();

  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledTimes(1);
  expect(api.reviewCard).toHaveBeenCalledWith(AIRPORT.id, 'good');
  expect(screen.queryByText('la canción')).toBeNull();
});

/** A reviewCard that stays pending until the test resolves it. */
function heldReview() {
  let resolve;
  const reviewCard = vi.fn(() => new Promise((done) => { resolve = done; }));
  return { reviewCard, finish: (value) => resolve(value) };
}

test('Good clicked twice in quick succession saves once', async () => {
  const held = heldReview();
  const { api } = renderView(fakeApi({ reviewCard: held.reviewCard }));
  await screen.findByText('the airport');
  showAnswer();

  const good = ratingButton('Good');
  fireEvent.click(good);
  fireEvent.click(good);
  held.finish(reviewed(AIRPORT));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledTimes(1);
});

test('3 pressed twice saves once', async () => {
  const held = heldReview();
  const { api } = renderView(fakeApi({ reviewCard: held.reviewCard }));
  await screen.findByText('the airport');
  showAnswer();

  press('3');
  press('3');
  held.finish(reviewed(AIRPORT));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledTimes(1);
  expect(api.reviewCard).toHaveBeenCalledWith(AIRPORT.id, 'good');
});

// The plan says to ignore key events from buttons, but a button does nothing with a
// digit, so a keyboard user who has tabbed onto a rating button can still press 1-4.
test('a digit pressed while a rating button has focus still rates', async () => {
  const { api } = renderView();
  await screen.findByText('the airport');
  showAnswer();

  fireEvent.keyDown(ratingButton('Again'), { key: '4' });

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledWith(AIRPORT.id, 'easy');
});

test('a conflict skips to the next card without counting the answer', async () => {
  const reviewCard = vi.fn()
    .mockRejectedValueOnce(apiError('conflict', "Card isn't due yet"))
    .mockResolvedValueOnce(reviewed(SONG));
  renderView(fakeApi({ reviewCard }));
  await screen.findByText('the airport');
  showAnswer();

  fireEvent.click(ratingButton('Good'));
  expect(await screen.findByText('the song')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();

  showAnswer();
  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByRole('heading', { name: 'Session complete' })).toBeTruthy();
  // One Good, from the song: the skipped airport isn't counted.
  expect(summaryText()).toMatch(/good\s*1(?!\d)/i);
});

test('a network error keeps the card revealed, shows an alert, and lets Good try again', async () => {
  const reviewCard = vi.fn()
    .mockRejectedValueOnce(apiError('network_error', "Can't reach the server."))
    .mockResolvedValueOnce(reviewed(AIRPORT));
  renderView(fakeApi({ reviewCard }));
  await screen.findByText('the airport');
  showAnswer();

  fireEvent.click(ratingButton('Good'));

  expect((await screen.findByRole('alert')).textContent).toBe("Can't reach the server.");
  expect(screen.getByText('el aeropuerto')).toBeTruthy();
  expect(ratingButton('Good').disabled).toBe(false);

  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(reviewCard).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('alert')).toBeNull();
});

test('the only card left, back as learning in 10 minutes, shows again unrevealed', async () => {
  const reviewCard = vi.fn().mockResolvedValue({ ...SONG, state: 'learning', due_at: iso(NOW + 10 * MINUTE) });
  renderView(fakeApi({ dueCards: due({ fresh: [SONG] }), reviewCard }));
  await screen.findByText('the song');
  showAnswer();

  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByRole('button', { name: 'Show answer' })).toBeTruthy();
  expect(screen.getByText('the song')).toBeTruthy();
  expect(screen.queryByText('la canción')).toBeNull();
});

test('rating the last card shows the summary with the counts', async () => {
  renderView(fakeApi({ dueCards: due({ review: [AIRPORT] }) }));
  await screen.findByText('the airport');
  showAnswer();

  fireEvent.click(ratingButton('Easy'));

  expect(await screen.findByRole('heading', { name: 'Session complete' })).toBeTruthy();
  expect(summaryText()).toMatch(/easy\s*1(?!\d)/i);
  expect(summaryText()).toMatch(/good\s*0(?!\d)/i);
});

test('nothing due goes straight to the summary empty state', async () => {
  renderView(fakeApi({ dueCards: due() }));

  expect(await screen.findByRole('heading', { name: 'Nothing to study right now' })).toBeTruthy();
});

test('a deck that does not exist says so, with a way back', async () => {
  const api = fakeApi();
  api.getDeck.mockRejectedValue(apiError('not_found', 'Deck not found.'));
  const { onExit } = renderView(api);

  expect(await screen.findByText('This deck could not be found.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Back to deck' }));
  expect(onExit).toHaveBeenCalledTimes(1);
});

test('any other load failure shows the message and Try again loads again', async () => {
  const api = fakeApi();
  api.getDueCards.mockRejectedValueOnce(apiError('network_error', "Can't reach the server."));
  renderView(api);

  expect(await screen.findByText("Can't reach the server.")).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

  expect(await screen.findByText('the airport')).toBeTruthy();
  expect(api.getDueCards).toHaveBeenCalledTimes(2);
});

test('Study more on the summary fetches again and starts a new session', async () => {
  // Only a learning card beyond the 20-minute learn-ahead window: the session finishes
  // at once, and the summary offers Study more.
  const later = card(3, 'the ticket', 'el boleto', 'learning', NOW + 30 * MINUTE);
  const api = fakeApi({ dueCards: due({ learning: [later] }) });
  api.getDueCards.mockResolvedValueOnce(due({ learning: [later] }))
    .mockResolvedValueOnce(due({ fresh: [SONG] }));
  renderView(api);

  fireEvent.click(await screen.findByRole('button', { name: 'Study more' }));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.getDueCards).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: 'Show answer' })).toBeTruthy();
});
