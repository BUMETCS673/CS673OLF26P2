// @vitest-environment jsdom

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createTutorApi } from '../src/api/tutor.js';
import { DeckDetailView } from '../src/pages/DeckDetailPage.jsx';
import { TutorView } from '../src/pages/TutorPage.jsx';

afterEach(cleanup);

const EMPTY = { enabled: true, status: 'idle', messages: [], proposal: null };
const CHAT = {
  ...EMPTY,
  messages: [
    { role: 'user', text: 'Where does it happen?', error: false },
    { role: 'tutor', text: 'What does it break down?', error: false },
  ],
};
const PROPOSAL = {
  id: 'proposal-1',
  verification: 'passed',
  cards: [{ front: 'Which cycle?', back: 'Krebs cycle' }],
};
const apiError = (code, message) => Object.assign(new Error(message), { code });

function fakeApi(overrides = {}) {
  return {
    getTutor: vi.fn().mockResolvedValue(EMPTY),
    sendMessage: vi.fn().mockResolvedValue(CHAT),
    decideProposal: vi.fn().mockResolvedValue(CHAT),
    resetTutor: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

async function open(api = fakeApi()) {
  render(<TutorView api={api} deckId="2" onExit={vi.fn()} />);
  await screen.findByRole('heading', { name: 'Ask about this deck' });
  return api;
}

const input = () => screen.getByLabelText('Your message');
const type = (text) => fireEvent.change(input(), { target: { value: text } });
const button = (name) => screen.getByRole('button', { name });

test('the API calls the four routes', () => {
  const request = vi.fn();
  const api = createTutorApi(request);

  api.getTutor(2);
  api.sendMessage(2, 'Hi');
  api.decideProposal(2, 'p', true);
  api.resetTutor(2);

  expect(request.mock.calls).toEqual([
    ['/api/decks/2/tutor'],
    ['/api/decks/2/tutor/messages', { method: 'POST', body: { text: 'Hi' } }],
    ['/api/decks/2/tutor/proposal', { method: 'POST', body: { proposal_id: 'p', accept: true } }],
    ['/api/decks/2/tutor', { method: 'DELETE' }],
  ]);
});

test('an empty chat explains itself, and warns about privacy', async () => {
  await open();

  expect(screen.getByText(/hints first/)).toBeTruthy();
  expect(screen.getByText(/sent to Google's AI/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Reset chat' })).toBeNull();
});

test('sending shows the message right away, then the reply', async () => {
  let finish;
  const api = await open(fakeApi({
    sendMessage: vi.fn(() => new Promise((resolve) => { finish = resolve; })),
  }));

  type('Where does it happen?');
  fireEvent.click(button('Send'));

  expect(screen.getByText('Where does it happen?')).toBeTruthy();
  expect(screen.getByText('Thinking…')).toBeTruthy();
  expect(input().value).toBe('');

  finish(CHAT);

  expect(await screen.findByText('What does it break down?')).toBeTruthy();
  expect(screen.queryByText('Thinking…')).toBeNull();
  expect(api.sendMessage).toHaveBeenCalledWith('2', 'Where does it happen?');
});

test('a blank message is not sent', async () => {
  await open();
  type('   ');
  expect(button('Send').disabled).toBe(true);
});

test('Quiz me sends the request', async () => {
  const api = await open();

  fireEvent.click(button('Quiz me'));

  await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('2', 'Quiz me on my weak cards.'));
});

test('a double click sends once', async () => {
  const api = await open();
  type('Hello');
  const send = button('Send');

  fireEvent.click(send);
  fireEvent.click(send);

  await screen.findByText('What does it break down?');
  expect(api.sendMessage).toHaveBeenCalledTimes(1);
});

test('a failed send shows the error and puts the text back', async () => {
  await open(fakeApi({ sendMessage: vi.fn().mockRejectedValue(apiError('rate_limited', 'Try later.')) }));

  type('Hello');
  fireEvent.click(button('Send'));

  expect((await screen.findByRole('alert')).textContent).toBe('Try later.');
  expect(input().value).toBe('Hello');
});

test('a 401 shows no error, because the adapter signs out', async () => {
  await open(fakeApi({ sendMessage: vi.fn().mockRejectedValue(apiError('unauthorized', 'Sign in.')) }));

  type('Hello');
  fireEvent.click(button('Send'));

  await waitFor(() => expect(input().disabled).toBe(false));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('text from the model shows as plain text, not markup', async () => {
  const text = '<img src=x onerror="alert(1)"> **bold**';
  await open(fakeApi({
    getTutor: vi.fn().mockResolvedValue({ ...EMPTY, messages: [{ role: 'tutor', text, error: false }] }),
  }));

  expect(screen.getByText(text)).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
});

test('a proposal blocks new messages until the learner decides', async () => {
  await open(fakeApi({ getTutor: vi.fn().mockResolvedValue({ ...CHAT, proposal: PROPOSAL }) }));

  expect(screen.getByText('Which cycle? → Krebs cycle')).toBeTruthy();
  expect(input().disabled).toBe(true);
  expect(button('Quiz me').disabled).toBe(true);
});

test.each([['Add to deck', true], ['No thanks', false]])('%s sends the proposal id', async (name, accept) => {
  const api = await open(fakeApi({ getTutor: vi.fn().mockResolvedValue({ ...CHAT, proposal: PROPOSAL }) }));

  fireEvent.click(button(name));

  await waitFor(() => expect(api.decideProposal).toHaveBeenCalledWith('2', 'proposal-1', accept));
  await waitFor(() => expect(screen.queryByText('Suggested cards')).toBeNull());
});

test('a skipped accuracy check says so', async () => {
  const proposal = { ...PROPOSAL, verification: 'skipped' };
  await open(fakeApi({ getTutor: vi.fn().mockResolvedValue({ ...CHAT, proposal }) }));

  expect(screen.getByText(/accuracy check didn't run/)).toBeTruthy();
});

test('resetting asks first, then clears the chat', async () => {
  const getTutor = vi.fn().mockResolvedValueOnce(CHAT).mockResolvedValue(EMPTY);
  const api = await open(fakeApi({ getTutor }));

  fireEvent.click(button('Reset chat'));
  expect(api.resetTutor).not.toHaveBeenCalled();
  fireEvent.click(button('Delete chat'));

  await screen.findByText(/hints first/);
  expect(api.resetTutor).toHaveBeenCalledWith('2');
});

test('turned off, it says so and blocks sending', async () => {
  await open(fakeApi({ getTutor: vi.fn().mockResolvedValue({ ...EMPTY, enabled: false }) }));

  expect(screen.getByText("The tutor isn't available right now.")).toBeTruthy();
  expect(input().disabled).toBe(true);
});

test('a failed load shows the error', async () => {
  render(<TutorView api={fakeApi({ getTutor: vi.fn().mockRejectedValue(apiError('not_found', 'Deck not found')) })}
    deckId="2" onExit={vi.fn()} />);

  expect(await screen.findByRole('alert')).toBeTruthy();
});

test('the deck page opens the tutor', async () => {
  const onAskTutor = vi.fn();
  const api = {
    getDeck: vi.fn().mockResolvedValue({ id: 2, name: 'Biology', description: null }),
    listCards: vi.fn().mockResolvedValue([]),
  };
  render(<DeckDetailView api={api} deckId="2" onBack={vi.fn()} onStudy={vi.fn()} onGenerate={vi.fn()}
    onAskTutor={onAskTutor} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Ask tutor' }));
  expect(onAskTutor).toHaveBeenCalled();
});
