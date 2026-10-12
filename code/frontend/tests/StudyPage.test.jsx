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

test('a digit that lands between the response and the re-render saves nothing more', async () => {
  const held = heldReview();
  const { api } = renderView(fakeApi({ reviewCard: held.reviewCard }));
  await screen.findByText('the airport');
  showAnswer();

  press('3');
  held.finish(reviewed(AIRPORT));
  for (let i = 0; i < 10; i += 1) await Promise.resolve();  // finally has run; no re-render yet
  press('3');

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledTimes(1);
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

// F6 (Iteration 3): typed mode on the study page. One test per acceptance example under F6
// in code/plans/ITERATION_3_PLAN.md, with the same fake `api` and fixed clock as above.
//
// AI Utilization: ~100% of the tests below
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F6 in the plan), direction, and review by Nurzat Mukhamedali.

const mode = (name) => screen.getByRole('radio', { name });
const answerBox = () => screen.queryByLabelText('Your answer');
const focused = () => screen.getByRole('main').ownerDocument.activeElement;

async function startTyped(api = fakeApi()) {
  renderView(api);
  await screen.findByText('the airport');
  fireEvent.click(mode('Typed answer'));
  return api;
}

function submitTyped(text) {
  fireEvent.change(answerBox(), { target: { value: text } });
  // jsdom doesn't turn Enter into a submit, so submit the form the way the browser would.
  fireEvent.submit(answerBox().form);
}

test('typed mode: the page loads with "Flashcard" checked and Show answer showing', async () => {
  renderView();
  await screen.findByText('the airport');

  expect(mode('Flashcard').checked).toBe(true);
  expect(screen.getByRole('button', { name: 'Show answer' })).toBeTruthy();
  expect(answerBox()).toBeNull();
});

test('typed mode: choosing "Typed answer" shows a focused box, no Show answer, and no back', async () => {
  await startTyped();

  expect(answerBox()).toBeTruthy();
  expect(focused()).toBe(answerBox());
  expect(screen.queryByRole('button', { name: 'Show answer' })).toBeNull();
  expect(screen.queryByText('el aeropuerto')).toBeNull();
  expect(screen.getByText('Press Enter to check')).toBeTruthy();
});

test('typed mode, the airport card: "El Aeropuerto." + Enter is Correct, Good suggested and focused, nothing saved yet', async () => {
  const api = await startTyped();

  submitTyped('El Aeropuerto.');

  expect(screen.getByText('Correct')).toBeTruthy();
  expect(screen.getByText('el aeropuerto')).toBeTruthy();
  expect(screen.getByText('You typed: El Aeropuerto.')).toBeTruthy();
  const good = ratingButton('Good');
  expect(good.classList.contains('rating-suggested')).toBe(true);
  expect(good.getAttribute('aria-label')).toMatch(/, suggested$/);
  expect(focused()).toBe(good);
  expect(api.reviewCard).not.toHaveBeenCalled();
  expect(screen.getByText('Press Enter to accept the suggestion, or 1–4 to choose')).toBeTruthy();
});

test('typed mode, the same: Enter again saves Good once', async () => {
  const api = await startTyped();
  submitTyped('El Aeropuerto.');

  // Enter on a focused button is a click; jsdom doesn't make that translation itself.
  fireEvent.click(focused());

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledTimes(1);
  expect(api.reviewCard).toHaveBeenCalledWith(AIRPORT.id, 'good');
});

test('typed mode: "el aeropuerta" + Check is Incorrect, with Again suggested', async () => {
  await startTyped();

  fireEvent.change(answerBox(), { target: { value: 'el aeropuerta' } });
  fireEvent.click(screen.getByRole('button', { name: 'Check' }));

  expect(screen.getByText('Incorrect')).toBeTruthy();
  expect(ratingButton('Again').classList.contains('rating-suggested')).toBe(true);
  expect(ratingButton('Good').classList.contains('rating-suggested')).toBe(false);
  expect(focused()).toBe(ratingButton('Again'));
});

test('typed mode, graded with Again suggested: clicking Easy saves easy', async () => {
  const api = await startTyped();
  submitTyped('el aeropuerta');

  fireEvent.click(ratingButton('Easy'));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(api.reviewCard).toHaveBeenCalledWith(AIRPORT.id, 'easy');
});

test('typed mode: submitting blank is Incorrect, with Again suggested', async () => {
  await startTyped();

  submitTyped('');

  expect(screen.getByText('Incorrect')).toBeTruthy();
  expect(ratingButton('Again').classList.contains('rating-suggested')).toBe(true);
});

test('typed mode, the box focused: Space types a space and reveals nothing', async () => {
  await startTyped();

  const notPrevented = fireEvent.keyDown(answerBox(), { key: ' ' });

  expect(notPrevented).toBe(true);
  expect(screen.queryByText('el aeropuerto')).toBeNull();
  expect(ratingButton('Good')).toBeNull();
});

test('typed mode, focus elsewhere: Space reveals nothing either', async () => {
  await startTyped();

  press(' ');

  expect(screen.queryByText('el aeropuerto')).toBeNull();
  expect(answerBox()).toBeTruthy();
});

test('flashcard mode, right after clicking the toggle: Space reveals the answer', async () => {
  await startTyped();
  fireEvent.click(mode('Flashcard'));

  fireEvent.keyDown(mode('Flashcard'), { key: ' ' });

  expect(screen.getByText('el aeropuerto')).toBeTruthy();
  expect(ratingButton('Good')).toBeTruthy();
});

test('graded in typed mode, then "Flashcard": the buttons and suggestion stay; the next card has Show answer', async () => {
  await startTyped();
  submitTyped('El Aeropuerto.');

  fireEvent.click(mode('Flashcard'));

  expect(ratingButton('Good').classList.contains('rating-suggested')).toBe(true);
  expect(screen.getByText('Correct')).toBeTruthy();
  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Show answer' })).toBeTruthy();
  expect(answerBox()).toBeNull();
});

test('typed mode, the summary showing: Study more starts the new session still in typed mode', async () => {
  // The rated card comes back as learning beyond the learn-ahead window, so the summary
  // offers Study more.
  const reviewCard = vi.fn().mockResolvedValue(
    { ...AIRPORT, state: 'learning', due_at: iso(NOW + 30 * MINUTE) });
  const api = fakeApi({ reviewCard });
  api.getDueCards.mockResolvedValueOnce(due({ review: [AIRPORT] }))
    .mockResolvedValueOnce(due({ fresh: [SONG] }));
  await startTyped(api);
  submitTyped('el aeropuertx');
  fireEvent.click(ratingButton('Again'));

  fireEvent.click(await screen.findByRole('button', { name: 'Study more' }));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(answerBox()).toBeTruthy();
  expect(mode('Typed answer').checked).toBe(true);
});

test('typed mode, a card rated: the next card shows with its box empty and focused', async () => {
  await startTyped();
  submitTyped('el aeropuerto');

  fireEvent.click(ratingButton('Good'));

  expect(await screen.findByText('the song')).toBeTruthy();
  expect(answerBox().value).toBe('');
  expect(focused()).toBe(answerBox());
});

test('typed mode: the same card back as learning gets a fresh, empty box', async () => {
  const reviewCard = vi.fn().mockResolvedValue({ ...SONG, state: 'learning', due_at: iso(NOW + 10 * MINUTE) });
  renderView(fakeApi({ dueCards: due({ fresh: [SONG] }), reviewCard }));
  await screen.findByText('the song');
  fireEvent.click(mode('Typed answer'));
  submitTyped('la cancion');

  fireEvent.click(ratingButton('Again'));

  await vi.waitFor(() => expect(answerBox()).toBeTruthy());
  expect(answerBox().value).toBe('');
  expect(screen.queryByText('Incorrect')).toBeNull();
});
