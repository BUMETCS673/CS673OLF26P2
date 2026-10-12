// @vitest-environment jsdom
//
// Step 0b: the generate page. GenerateView takes a fake `api` (rule 12), and its two
// children are replaced with stand-ins that record the props they're given, so these
// tests cover GenerateView's wiring and nothing of F1's or F2's markup (decision A17).
// Only the route tests at the end render the real App, with fetch mocked.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import App from '../src/App.jsx';
import GeneratePage, { GenerateView } from '../src/pages/GeneratePage.jsx';

// The latest props each child was rendered with, or null if it isn't on the page.
const shown = vi.hoisted(() => ({ form: null, list: null }));
vi.mock('../src/components/generate/GenerateForm.jsx', () => ({
  default: (props) => { shown.form = props; return <p>Generate form</p>; },
}));
vi.mock('../src/components/generate/CandidateList.jsx', () => ({
  default: (props) => { shown.list = props; return <p>Candidate list</p>; },
}));

const auth = vi.hoisted(() => ({ user: null, loading: false, expireSession: () => {} }));
vi.mock('../src/auth/AuthContext.jsx', () => ({ useAuth: () => auth }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.assign(shown, { form: null, list: null });
  auth.user = null;
});

const DECK = { id: 2, name: 'Travel Spanish', description: null, card_count: 11 };
const candidate = (index, status = 'pending') =>
  ({ index, front: `Sample question ${index + 1}`, back: `Sample answer ${index + 1}`, status });
const GENERATION = {
  id: 7, deck_id: 2, mode: 'prompt', requested_count: 3, model: 'fake',
  created_at: '2026-10-09T14:00:00Z', cards: [candidate(0), candidate(1), candidate(2)],
};
const BODY = { mode: 'prompt', count: 3, prompt: 'Spanish greetings' };

/** GENERATION with the given indexes decided. */
const decided = (indexes, status) =>
  ({ ...GENERATION, cards: GENERATION.cards.map((c) => (indexes.includes(c.index) ? { ...c, status } : c)) });
const apiError = (code, message = 'Something went wrong') => Object.assign(new Error(message), { code });

function fakeApi(overrides = {}) {
  return {
    getDeck: vi.fn().mockResolvedValue(DECK),
    generate: vi.fn().mockResolvedValue(GENERATION),
    acceptCards: vi.fn(async (_id, indexes) => ({ cards: [], generation: decided(indexes, 'accepted') })),
    rejectCards: vi.fn(async (_id, indexes) => decided(indexes, 'rejected')),
    ...overrides,
  };
}

/** A function that stays pending until the test settles it. */
function held() {
  let resolve;
  let reject;
  const fn = vi.fn(() => new Promise((ok, fail) => { resolve = ok; reject = fail; }));
  return { fn, resolve: (value) => resolve(value), reject: (error) => reject(error) };
}

async function renderView(api = fakeApi(), onExit = vi.fn()) {
  render(<GenerateView api={api} deckId="2" onExit={onExit} />);
  await screen.findByText('Generate form');
  return { api, onExit };
}

/** Renders the view and generates, so the list is showing. */
async function renderList(api = fakeApi(), onExit = vi.fn()) {
  await renderView(api, onExit);
  await act(() => shown.form.onGenerate(BODY));
  return { api, onExit };
}

// --- loading the deck --------------------------------------------------------------------

test('while the deck loads, a status shows and neither child does', () => {
  render(<GenerateView api={fakeApi({ getDeck: held().fn })} deckId="2" onExit={vi.fn()} />);

  expect(screen.getByRole('status').textContent).toBe('Loading…');
  expect(shown.form).toBeNull();
  expect(shown.list).toBeNull();
});

test('a deck that does not exist says so, offers a way back, and no Try again', async () => {
  const onExit = vi.fn();
  const api = fakeApi({ getDeck: vi.fn().mockRejectedValue(apiError('not_found', 'Deck not found')) });
  render(<GenerateView api={api} deckId="2" onExit={onExit} />);

  expect((await screen.findByRole('alert')).textContent).toBe('This deck could not be found.');
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Back to deck' }));
  expect(onExit).toHaveBeenCalledTimes(1);
  expect(shown.form).toBeNull();
});

test('any other load error shows its message, and Try again loads the deck again', async () => {
  const getDeck = vi.fn()
    .mockRejectedValueOnce(apiError('network_error', "Can't reach the server."))
    .mockResolvedValueOnce(DECK);
  render(<GenerateView api={fakeApi({ getDeck })} deckId="2" onExit={vi.fn()} />);

  expect((await screen.findByRole('alert')).textContent).toBe("Can't reach the server.");
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

  expect(await screen.findByText('Generate form')).toBeTruthy();
  expect(getDeck).toHaveBeenCalledTimes(2);
});

// --- the page and the form ---------------------------------------------------------------

test('the deck name heads the page, and the form gets the deck and its card count', async () => {
  const { api } = await renderView();

  expect(api.getDeck).toHaveBeenCalledWith('2');
  expect(screen.getByRole('heading', { name: 'Travel Spanish' })).toBeTruthy();
  expect(shown.form).toMatchObject({ deck: DECK, cardCount: 11, busy: false, error: null });
  expect(shown.list).toBeNull();
});

test('← Back to deck in the heading calls onExit', async () => {
  const { onExit } = await renderView();

  fireEvent.click(screen.getByRole('button', { name: 'Back to deck' }));

  expect(onExit).toHaveBeenCalledTimes(1);
});

test('a successful generate gives the list the generation, and the form goes', async () => {
  const { api } = await renderList();

  expect(api.generate).toHaveBeenCalledWith('2', BODY);
  expect(screen.getByText('Candidate list')).toBeTruthy();
  expect(screen.queryByText('Generate form')).toBeNull();
  expect(shown.list).toMatchObject({ generation: GENERATION, busy: false, error: null });
});

test('while generating, the form is busy', async () => {
  const generate = held();
  await renderView(fakeApi({ generate: generate.fn }));

  let pending;
  act(() => { pending = shown.form.onGenerate(BODY); });
  expect(shown.form.busy).toBe(true);

  generate.resolve(GENERATION);
  await act(() => pending);
  expect(shown.list.generation).toBe(GENERATION);
});

test('a failed generate gives the form the error, and the form stays', async () => {
  const limited = apiError('rate_limited', "You've reached the limit of 10 AI generations in 24 hours.");
  const { api } = await renderView(fakeApi({ generate: vi.fn().mockRejectedValue(limited) }));

  await act(() => shown.form.onGenerate(BODY));

  expect(shown.form).toMatchObject({ error: limited, busy: false });
  expect(screen.getByText('Generate form')).toBeTruthy();
  expect(shown.list).toBeNull();

  // The learner can try again from the same form.
  api.generate.mockResolvedValueOnce(GENERATION);
  await act(() => shown.form.onGenerate(BODY));
  expect(shown.list.generation).toBe(GENERATION);
});

test('a 401 while generating shows no error, because the adapter signs the learner out', async () => {
  await renderView(fakeApi({ generate: vi.fn().mockRejectedValue(apiError('unauthorized')) }));

  await act(() => shown.form.onGenerate(BODY));

  expect(shown.form.error).toBeNull();
});

test('a second onGenerate while the first is in flight sends nothing (rule 21)', async () => {
  const generate = held();
  const { api } = await renderView(fakeApi({ generate: generate.fn }));

  let first;
  act(() => {
    first = shown.form.onGenerate(BODY);
    shown.form.onGenerate(BODY);
  });
  // Again after the re-render, from the busy form's own callback.
  act(() => { shown.form.onGenerate(BODY); });
  generate.resolve(GENERATION);
  await act(() => first);

  expect(api.generate).toHaveBeenCalledTimes(1);
  expect(shown.list.generation).toBe(GENERATION);
});

test('after a failed generate, the next one is sent', async () => {
  const generate = held();
  const { api } = await renderView(fakeApi({ generate: generate.fn }));

  let first;
  act(() => { first = shown.form.onGenerate(BODY); });
  generate.reject(apiError('ai_unavailable', "The AI service didn't respond."));
  await act(() => first);
  act(() => { shown.form.onGenerate(BODY); });

  expect(api.generate).toHaveBeenCalledTimes(2);
});

// --- the list ------------------------------------------------------------------------------

test('accept sends the generation id and the indexes, and the list gets the new generation', async () => {
  const { api } = await renderList();

  await act(() => shown.list.onAccept([0, 2]));

  expect(api.acceptCards).toHaveBeenCalledWith(7, [0, 2]);
  expect(shown.list.generation.cards.map((c) => c.status)).toEqual(['accepted', 'pending', 'accepted']);
  expect(shown.list.busy).toBe(false);
});

test('reject sends the generation id and the indexes, and the list gets the new generation', async () => {
  const { api } = await renderList();

  await act(() => shown.list.onReject([1]));

  expect(api.rejectCards).toHaveBeenCalledWith(7, [1]);
  expect(shown.list.generation.cards.map((c) => c.status)).toEqual(['pending', 'rejected', 'pending']);
});

test('while a decision is saving, the list is busy', async () => {
  const accept = held();
  await renderList(fakeApi({ acceptCards: accept.fn }));

  let pending;
  act(() => { pending = shown.list.onAccept([0]); });
  expect(shown.list.busy).toBe(true);

  accept.resolve({ cards: [], generation: decided([0], 'accepted') });
  await act(() => pending);
  expect(shown.list.busy).toBe(false);
});

test('a failed decision gives the list the error, and keeps the generation', async () => {
  const failure = apiError('network_error', "Can't reach the server.");
  await renderList(fakeApi({ rejectCards: vi.fn().mockRejectedValue(failure) }));

  await act(() => shown.list.onReject([1]));

  expect(shown.list).toMatchObject({ generation: GENERATION, error: failure, busy: false });
});

test('a 401 on a decision shows no error, because the adapter signs the learner out', async () => {
  await renderList(fakeApi({ acceptCards: vi.fn().mockRejectedValue(apiError('unauthorized')) }));

  await act(() => shown.list.onAccept([0]));

  expect(shown.list.error).toBeNull();
});

test('Generate more goes back to the form, with the deck loaded again', async () => {
  const getDeck = vi.fn()
    .mockResolvedValueOnce(DECK)
    .mockResolvedValueOnce({ ...DECK, card_count: 13 });
  const { api } = await renderList(fakeApi({ getDeck }));
  await act(() => shown.list.onAccept([0, 2]));

  act(() => shown.list.onGenerateMore());

  expect(await screen.findByText('Generate form')).toBeTruthy();
  expect(screen.queryByText('Candidate list')).toBeNull();
  expect(api.getDeck).toHaveBeenCalledTimes(2);
  expect(shown.form.cardCount).toBe(13);
});

test("Generate more clears the list's error, so the next batch starts clean", async () => {
  const failure = apiError('network_error', "Can't reach the server.");
  await renderList(fakeApi({ acceptCards: vi.fn().mockRejectedValue(failure) }));
  await act(() => shown.list.onAccept([0]));
  expect(shown.list.error).toBe(failure);

  act(() => shown.list.onGenerateMore());
  await screen.findByText('Generate form');
  expect(shown.form.error).toBeNull();
  await act(() => shown.form.onGenerate(BODY));

  expect(shown.list.error).toBeNull();
});

test('Back to deck from the list calls onExit', async () => {
  const { onExit } = await renderList();

  shown.list.onBackToDeck();

  expect(onExit).toHaveBeenCalledTimes(1);
});

// --- the route ---------------------------------------------------------------------------

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

/** Answers GET /api/decks/2 and POST /api/decks/2/generate, and records every call. */
function mockFetch() {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    calls.push({ url, method: options.method });
    return url.endsWith('/generate') ? json(GENERATION, 201) : json(DECK);
  });
  return calls;
}

test('signed in, /decks/2/generate shows the deck name and the form, on the real clients', async () => {
  auth.user = { id: 1, email: 'demo@cadence.local' };
  const calls = mockFetch();
  render(<MemoryRouter initialEntries={['/decks/2/generate']}><App /></MemoryRouter>);

  expect(await screen.findByRole('heading', { name: 'Travel Spanish' })).toBeTruthy();
  expect(screen.getByText('Generate form')).toBeTruthy();

  await act(() => shown.form.onGenerate(BODY));
  expect(calls).toEqual([
    { url: '/api/decks/2', method: 'GET' },
    { url: '/api/decks/2/generate', method: 'POST' },
  ]);
  expect(shown.list.generation).toEqual(GENERATION);
});

test('signed out, /decks/2/generate sends you to the login page', () => {
  render(<MemoryRouter initialEntries={['/decks/2/generate']}><App /></MemoryRouter>);

  expect(screen.getByRole('heading', { name: 'Sign in to Cadence' })).toBeTruthy();
  expect(shown.form).toBeNull();
});

test("the page's Back to deck goes to /decks/2", async () => {
  auth.user = { id: 1, email: 'demo@cadence.local' };
  mockFetch();
  render(
    <MemoryRouter initialEntries={['/decks/2/generate']}>
      <Routes>
        <Route path="/decks/:id/generate" element={<GeneratePage />} />
        <Route path="/decks/:id" element={<p>The deck page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText('Generate form');

  fireEvent.click(screen.getByRole('button', { name: 'Back to deck' }));

  expect(screen.getByText('The deck page')).toBeTruthy();
});
