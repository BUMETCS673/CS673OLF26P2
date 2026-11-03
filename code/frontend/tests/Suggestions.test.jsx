// @vitest-environment jsdom

import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import LeechBanner from '../src/components/LeechBanner.jsx';
import SuggestionsCard from '../src/components/SuggestionsCard.jsx';
import SuggestionsNotice from '../src/components/SuggestionsNotice.jsx';
import { DeckDetailView } from '../src/pages/DeckDetailPage.jsx';
import { DeckListView } from '../src/pages/DeckListPage.jsx';
import {
  MAX_POLLS,
  POLL_MS,
  SuggestionsContext,
  SuggestionsProvider,
  useSuggestions,
} from '../src/suggestions/SuggestionsContext.jsx';

const auth = vi.hoisted(() => ({ user: { id: 1 }, expireSession: () => {} }));
vi.mock('../src/auth/AuthContext', () => ({ useAuth: () => auth }));

const api = vi.hoisted(() => ({ refreshSuggestions: null }));
vi.mock('../src/api/useApi.js', () => ({ useApi: () => api }));

const BIOLOGY = { review_id: 3, deck_id: 2, deck_name: 'Biology', card_count: 3 };
const NONE = { processing: false, ready: [] };
const PROCESSING = { processing: true, ready: [] };
const READY = { processing: false, ready: [BIOLOGY] };

beforeEach(() => {
  auth.user = { id: 1 };
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const settle = () => act(() => vi.advanceTimersByTimeAsync(0));
const tick = (ms = POLL_MS) => act(() => vi.advanceTimersByTimeAsync(ms));

/** Exposes the router and the store, so a test can act like the rest of the app. */
const controls = {};
function Controls() {
  controls.navigate = useNavigate();
  controls.pathname = useLocation().pathname;
  controls.store = useSuggestions();
  return null;
}

async function mount(path = '/decks') {
  render(<MemoryRouter initialEntries={[path]}>
    <SuggestionsProvider>
      <Controls />
      <SuggestionsNotice />
    </SuggestionsProvider>
  </MemoryRouter>);
  await settle();
}

const noticeButton = () => screen.queryByRole('button', { name: 'See suggestions' });

test('a job finishing shows the notice without a reload, then checks stop', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(PROCESSING).mockResolvedValue(READY);
  await mount();
  expect(noticeButton()).toBeNull();

  await tick();

  expect(screen.getByRole('status').textContent).toContain('Biology:');
  expect(screen.getByRole('status').textContent).toContain('3 cards');
  const calls = api.refreshSuggestions.mock.calls.length;
  await tick(POLL_MS * 3);
  expect(api.refreshSuggestions.mock.calls.length).toBe(calls);
});

test('suggestions already ready at the first check get no notice', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValue(READY);
  await mount();

  expect(noticeButton()).toBeNull();
  expect(controls.store.ready).toEqual([BIOLOGY]);
});

test('with no job running, nothing polls', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValue(NONE);
  await mount();

  await tick(POLL_MS * 5);

  expect(api.refreshSuggestions).toHaveBeenCalledTimes(1);
});

test('polling gives up after the maximum', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValue(PROCESSING);
  await mount();

  await tick(POLL_MS * (MAX_POLLS + 5));

  expect(api.refreshSuggestions).toHaveBeenCalledTimes(1 + MAX_POLLS);
});

test('changing page checks once', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValue(NONE);
  await mount();

  act(() => controls.navigate('/decks/2'));
  await settle();

  expect(api.refreshSuggestions).toHaveBeenCalledTimes(2);
});

test('returning to the tab checks once', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValue(NONE);
  await mount();

  act(() => globalThis.document.dispatchEvent(new globalThis.Event('visibilitychange')));
  await settle();

  expect(api.refreshSuggestions).toHaveBeenCalledTimes(2);
});

test('signed out, nothing is checked', async () => {
  auth.user = null;
  api.refreshSuggestions = vi.fn().mockResolvedValue(NONE);
  await mount();

  expect(api.refreshSuggestions).not.toHaveBeenCalled();
});

test("another user never sees the last user's suggestions", async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(READY).mockResolvedValue(new Promise(() => {}));
  const app = <MemoryRouter><SuggestionsProvider><Controls /></SuggestionsProvider></MemoryRouter>;
  const { rerender } = render(app);
  await settle();
  expect(controls.store.ready).toEqual([BIOLOGY]);

  auth.user = { id: 2 };
  rerender(<MemoryRouter><SuggestionsProvider><Controls /></SuggestionsProvider></MemoryRouter>);
  await settle();

  expect(controls.store.ready).toEqual([]);
});

test('a failed check leaves the store as it is', async () => {
  api.refreshSuggestions = vi.fn().mockRejectedValue(new Error('down'));
  await mount();

  expect(controls.store.ready).toEqual([]);
  expect(controls.store.processing).toBe(false);
});

test('during a study session nothing is checked, and the end of it starts the job', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(PROCESSING).mockResolvedValue(READY);
  await mount('/decks/2/study');
  expect(api.refreshSuggestions).not.toHaveBeenCalled();

  act(() => controls.store.setSessionDone(true));
  await settle();
  expect(api.refreshSuggestions).toHaveBeenCalledTimes(1);

  await tick();
  expect(noticeButton()).toBeTruthy();
});

test('polling stops during a study session and the notice appears after it', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(PROCESSING).mockResolvedValue(READY);
  await mount();
  act(() => controls.navigate('/decks/2/study'));
  await tick(POLL_MS * 3);

  expect(api.refreshSuggestions).toHaveBeenCalledTimes(1);
  expect(noticeButton()).toBeNull();

  act(() => controls.navigate('/decks'));
  await settle();
  expect(noticeButton()).toBeTruthy();
});

test('See suggestions opens the review page and closes the notice', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(PROCESSING).mockResolvedValue(READY);
  await mount();
  await tick();

  fireEvent.click(noticeButton());
  await settle();

  expect(controls.pathname).toBe('/decks/2/leeches');
  expect(noticeButton()).toBeNull();
});

test('Close hides the notice, and the suggestion stays in the store', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(PROCESSING).mockResolvedValue(READY);
  await mount();
  await tick();

  fireEvent.click(screen.getByRole('button', { name: 'Close' }));

  expect(noticeButton()).toBeNull();
  expect(controls.store.ready).toEqual([BIOLOGY]);
});

test('finishing the review removes the suggestion everywhere', async () => {
  api.refreshSuggestions = vi.fn().mockResolvedValueOnce(READY).mockResolvedValue(NONE);
  await mount();

  await act(() => controls.store.refresh());

  expect(controls.store.ready).toEqual([]);
});

function withSuggestions(ui, ready = [BIOLOGY]) {
  return <SuggestionsContext.Provider value={{ ready }}>{ui}</SuggestionsContext.Provider>;
}

test('the home card lists each deck and opens its review', () => {
  const onReview = vi.fn();
  render(withSuggestions(<SuggestionsCard onReview={onReview} />));

  expect(screen.getByText('Biology: 3 cards')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Review suggestions for Biology' }));
  expect(onReview).toHaveBeenCalledWith(2);
});

test('the home card hides with nothing ready', () => {
  const { container } = render(withSuggestions(<SuggestionsCard onReview={vi.fn()} />, []));
  expect(container.textContent).toBe('');
});

test('the deck banner shows only for its own deck', () => {
  const onReview = vi.fn();
  const { rerender } = render(withSuggestions(<LeechBanner deckId="2" onReview={onReview} />));

  expect(screen.getByText('You keep forgetting 3 cards. I have some suggestions.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'See suggestions' }));
  expect(onReview).toHaveBeenCalled();

  rerender(withSuggestions(<LeechBanner deckId="9" onReview={onReview} />));
  expect(screen.queryByRole('button', { name: 'See suggestions' })).toBeNull();
});

test('the deck list page shows the home card', async () => {
  const deckApi = { listDecks: vi.fn().mockResolvedValue([]) };
  render(withSuggestions(<DeckListView api={deckApi} onOpenDeck={vi.fn()} onStudyDeck={vi.fn()} onReviewSuggestions={vi.fn()} />));
  await settle();

  expect(screen.getByRole('heading', { name: 'Suggestions for you' })).toBeTruthy();
});

test('the deck page shows the banner', async () => {
  const deckApi = {
    getDeck: vi.fn().mockResolvedValue({ id: 2, name: 'Biology', description: null }),
    listCards: vi.fn().mockResolvedValue([]),
  };
  render(withSuggestions(<DeckDetailView api={deckApi} deckId="2" onBack={vi.fn()} onStudy={vi.fn()}
    onGenerate={vi.fn()} onReviewLeeches={vi.fn()} />));
  await settle();

  expect(screen.getByRole('button', { name: 'See suggestions' })).toBeTruthy();
});
