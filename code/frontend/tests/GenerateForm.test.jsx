// @vitest-environment jsdom
//
// F1: the generate form. One test per acceptance example under F1 in
// code/plans/ITERATION_3_PLAN.md, plus the checks and edge cases around them. The form
// is rendered on its own with props (rule 12); file reads are real FileReader reads in
// jsdom, awaited, except where a test needs one to fail or hang.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation (from the plan's acceptance examples)
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import GenerateForm from '../src/components/generate/GenerateForm.jsx';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DECK = { id: 2, name: 'Travel Spanish', description: null, card_count: 12 };
const COUNT_RANGE = 'Choose between 1 and 25 cards.';
const PRIVACY = "Your prompt or file is sent to Google Gemini. Don't include personal or confidential information.";

const MATERIAL = {
  id: 7, filename: 'notes.pdf', status: 'ready', stage: 'finding_topics',
  chunks_done: 3, chunks_total: 3, suggested_topics: ['Mitosis', 'Enzymes'], error: null,
};
const QUESTION = 'What do you want to focus on?';

function renderForm(props = {}, uploaded = MATERIAL) {
  const onGenerate = vi.fn().mockResolvedValue(undefined);
  const materialsApi = {
    upload: vi.fn().mockResolvedValue(uploaded),
    getMaterial: vi.fn().mockResolvedValue(uploaded),
  };
  render(<GenerateForm deck={DECK} busy={false} error={null} onGenerate={onGenerate}
    materialsApi={materialsApi} {...props} />);
  return { onGenerate: props.onGenerate ?? onGenerate, materialsApi };
}

const radio = (name) => screen.getByRole('radio', { name });
const generateButton = () => screen.getByRole('button', { name: 'Generate' });
const generate = () => fireEvent.click(generateButton());
const fill = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const FILE = new File(['Cells divide.'], 'notes.pdf');

function chooseFile(file = FILE) {
  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [file] } });
}

/** Chooses a file, clicks Generate, and waits for the topic question. */
async function upToTheQuestion() {
  chooseFile();
  generate();
  return screen.findByLabelText(QUESTION);
}

// --- the form as it first appears ----------------------------------------------------

test('it starts on Write a prompt, with two modes, 10 cards and a Topic box', () => {
  renderForm();

  const group = screen.getByRole('group', { name: 'Generate from' });
  expect(group).toBeTruthy();
  expect(screen.getAllByRole('radio')).toHaveLength(2);
  expect(radio('Write a prompt').checked).toBe(true);
  expect(radio('Upload a file').checked).toBe(false);
  expect(screen.getByLabelText('How many cards?').value).toBe('10');
  expect(screen.getByLabelText('Topic')).toBeTruthy();
  expect(screen.queryByLabelText('File')).toBeNull();
});

test('the privacy line shows in every mode', () => {
  renderForm();

  for (const mode of ['Write a prompt', 'Upload a file']) {
    fireEvent.click(radio(mode));
    expect(screen.getByText(PRIVACY)).toBeTruthy();
  }
});

// --- Suggest something ----------------------------------------------------------------

const suggestButton = () => screen.getByRole('button', { name: 'Suggest something' });

function renderSuggesting(onSuggest = vi.fn().mockResolvedValue({ topics: ['Mitosis', 'ATP'] })) {
  return { ...renderForm({ onSuggest }), onSuggest };
}

test('Suggest something shows topics, and doesnt generate anything', async () => {
  const { onGenerate, onSuggest } = renderSuggesting();

  fireEvent.click(suggestButton());

  expect(await screen.findByRole('button', { name: 'Mitosis' })).toBeTruthy();
  expect(onSuggest).toHaveBeenCalledTimes(1);
  expect(onGenerate).not.toHaveBeenCalled();
});

test('it says when its thinking, and locks the button until the answer', async () => {
  let answer;
  renderSuggesting(() => new Promise((resolve) => { answer = resolve; }));

  fireEvent.click(suggestButton());

  expect(screen.getByText('Thinking of topics…')).toBeTruthy();
  expect(suggestButton().disabled).toBe(true);

  answer({ topics: ['Mitosis'] });

  expect(await screen.findByRole('button', { name: 'Mitosis' })).toBeTruthy();
  expect(suggestButton().disabled).toBe(false);
  expect(screen.queryByText('Thinking of topics…')).toBeNull();
});

test('picking a topic fills the prompt, and Generate sends it', async () => {
  const { onGenerate } = renderSuggesting();
  fireEvent.click(suggestButton());

  fireEvent.click(await screen.findByRole('button', { name: 'Mitosis' }));

  expect(screen.getByLabelText('Topic').value).toBe('Mitosis');
  expect(screen.queryByRole('button', { name: 'ATP' })).toBeNull();
  expect(onGenerate).not.toHaveBeenCalled();

  generate();
  expect(onGenerate).toHaveBeenCalledWith({ mode: 'prompt', count: 10, prompt: 'Mitosis' });
});

test('picking a topic from file mode moves to prompt mode', async () => {
  renderSuggesting();
  fireEvent.click(radio('Upload a file'));
  fireEvent.click(suggestButton());

  fireEvent.click(await screen.findByRole('button', { name: 'ATP' }));

  expect(radio('Write a prompt').checked).toBe(true);
  expect(screen.getByLabelText('Topic').value).toBe('ATP');
});

test('a failed request shows its message, and can be tried again', async () => {
  const onSuggest = vi.fn()
    .mockRejectedValueOnce(new Error('The AI service didnt respond.'))
    .mockResolvedValueOnce({ topics: ['Mitosis'] });
  renderSuggesting(onSuggest);

  fireEvent.click(suggestButton());
  expect((await screen.findByRole('alert')).textContent).toBe('The AI service didnt respond.');

  fireEvent.click(suggestButton());
  expect(await screen.findByRole('button', { name: 'Mitosis' })).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

test('an empty answer says so', async () => {
  renderSuggesting(vi.fn().mockResolvedValue({ topics: [] }));

  fireEvent.click(suggestButton());

  expect(await screen.findByText('No suggestions this time. Try again.')).toBeTruthy();
});

test('Suggest something is locked while cards are generating', () => {
  renderForm({ busy: true });

  expect(suggestButton().disabled).toBe(true);
});

// --- Write a prompt -------------------------------------------------------------------

test('Write a prompt sends the topic, trimmed, and the count as a number', () => {
  const { onGenerate } = renderForm();

  fill('Topic', '  Cells  ');
  generate();

  expect(onGenerate).toHaveBeenCalledTimes(1);
  expect(onGenerate).toHaveBeenCalledWith({ mode: 'prompt', count: 10, prompt: 'Cells' });
  expect(typeof onGenerate.mock.calls[0][0].count).toBe('number');
});

test('an empty Topic is caught before anything is sent', () => {
  const { onGenerate } = renderForm();

  fill('Topic', '   ');
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Describe what the cards should cover.')).toBeTruthy();
  expect(screen.getByLabelText('Topic').getAttribute('aria-invalid')).toBe('true');
});

test('a failed check focuses the first field with a problem, whose message describes it', () => {
  renderForm();

  fill('How many cards?', '0');
  generate();

  const count = screen.getByLabelText('How many cards?');
  expect(count.ownerDocument.activeElement).toBe(count);
  expect(count.ownerDocument.getElementById(count.getAttribute('aria-describedby')).textContent).toBe(COUNT_RANGE);
});

test('field messages are not alerts, so the one alert is the server\'s error', () => {
  renderForm();

  generate();

  expect(screen.queryByRole('alert')).toBeNull();
});

test('a Topic over 2,000 characters is caught', () => {
  const { onGenerate } = renderForm();

  fill('Topic', 'x'.repeat(2001));
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Keep the topic to 2,000 characters or fewer.')).toBeTruthy();
});

test('typing in a field clears its error', () => {
  renderForm();
  generate();
  expect(screen.getByText('Describe what the cards should cover.')).toBeTruthy();

  fill('Topic', 'Cells');

  expect(screen.queryByText('Describe what the cards should cover.')).toBeNull();
  expect(screen.getByLabelText('Topic').getAttribute('aria-invalid')).toBe('false');
});

test.each(['0', '26', '', '2.5'])('a count of "%s" is caught before anything is sent', (count) => {
  const { onGenerate } = renderForm();
  fill('Topic', 'Cells');

  fill('How many cards?', count);
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText(COUNT_RANGE)).toBeTruthy();
  expect(screen.getByLabelText('How many cards?').getAttribute('aria-invalid')).toBe('true');
});

test('counts of 1 and 25 are allowed', () => {
  const { onGenerate } = renderForm();
  fill('Topic', 'Cells');

  fill('How many cards?', '1');
  generate();
  fill('How many cards?', '25');
  generate();

  expect(onGenerate.mock.calls.map(([body]) => body.count)).toEqual([1, 25]);
});

// --- Upload a file --------------------------------------------------------------------

test('Upload a file starts with only the File input', () => {
  renderForm();

  fireEvent.click(radio('Upload a file'));

  expect(screen.getByLabelText('File')).toBeTruthy();
  expect(screen.queryByLabelText('Topic')).toBeNull();
  expect(screen.queryByLabelText('How many cards?')).toBeNull();
  expect(screen.queryByLabelText(QUESTION)).toBeNull();
});

test('Generate with no file says to choose one, and uploads nothing', () => {
  const { materialsApi } = renderForm();
  fireEvent.click(radio('Upload a file'));

  generate();

  expect(materialsApi.upload).not.toHaveBeenCalled();
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
  expect(globalThis.document.activeElement).toBe(screen.getByLabelText('File'));
});

test('choosing a file alone doesnt upload it', () => {
  const { materialsApi } = renderForm();

  chooseFile();

  expect(materialsApi.upload).not.toHaveBeenCalled();
});

test('the first Generate uploads the file, and sends no cards request', async () => {
  const { materialsApi, onGenerate } = renderForm();

  await upToTheQuestion();

  expect(materialsApi.upload).toHaveBeenCalledWith(FILE);
  expect(onGenerate).not.toHaveBeenCalled();
});

test('Generate is disabled while the file uploads and processes', async () => {
  renderForm({}, { ...MATERIAL, status: 'processing', stage: 'reading' });

  chooseFile();
  generate();
  expect(generateButton().disabled).toBe(true);

  expect(await screen.findByText('Reading your file…')).toBeTruthy();
  expect(generateButton().disabled).toBe(true);
  expect(screen.queryByLabelText(QUESTION)).toBeNull();
});

test('once ready, it asks for the topic and the count', async () => {
  renderForm();

  await upToTheQuestion();

  expect(screen.getByLabelText('How many cards?').value).toBe('10');
  expect(screen.getByRole('button', { name: 'Mitosis' })).toBeTruthy();
});

test('the second Generate sends the document, the trimmed topic and the count', async () => {
  const { onGenerate, materialsApi } = renderForm();
  await upToTheQuestion();

  fill(QUESTION, '  Cell cycle ');
  fill('How many cards?', '4');
  generate();

  expect(onGenerate).toHaveBeenCalledWith({
    mode: 'file', count: 4, document_id: 7, topic: 'Cell cycle',
  });
  expect(materialsApi.upload).toHaveBeenCalledTimes(1);
});

test('a suggested topic can be sent', async () => {
  const { onGenerate } = renderForm();
  await upToTheQuestion();

  fireEvent.click(screen.getByRole('button', { name: 'Enzymes' }));
  generate();

  expect(onGenerate.mock.calls[0][0].topic).toBe('Enzymes');
});

test('a topic is required, and typing clears the message', async () => {
  const { onGenerate } = renderForm();
  const input = await upToTheQuestion();

  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Say what you want to focus on.')).toBeTruthy();
  expect(globalThis.document.activeElement).toBe(input);

  fill(QUESTION, 'M');
  expect(screen.queryByText('Say what you want to focus on.')).toBeNull();
});

test('a failed file shows why, and Generate tries it again', async () => {
  const failed = { ...MATERIAL, status: 'failed', error: 'It failed.' };
  const { materialsApi } = renderForm({}, failed);

  chooseFile();
  generate();
  expect(await screen.findByText('It failed.')).toBeTruthy();
  expect(generateButton().disabled).toBe(false);

  generate();
  expect(materialsApi.upload).toHaveBeenCalledTimes(2);
});

test('a refused upload shows the server message', async () => {
  const { materialsApi } = renderForm();
  materialsApi.upload.mockRejectedValue(new Error('You have reached the limit.'));

  chooseFile();
  generate();

  expect(await screen.findByText('You have reached the limit.')).toBeTruthy();
});

test('choosing another file goes back to the first step', async () => {
  renderForm();
  await upToTheQuestion();
  fill(QUESTION, 'Mitosis');

  fireEvent.change(screen.getByLabelText('File'), {
    target: { files: [new File(['ATP'], 'other.txt')] },
  });

  expect(screen.queryByLabelText(QUESTION)).toBeNull();
  expect(screen.queryByLabelText('How many cards?')).toBeNull();
});

test('leaving file mode forgets the file', async () => {
  const { materialsApi } = renderForm();
  await upToTheQuestion();

  fireEvent.click(radio('Write a prompt'));
  fireEvent.click(radio('Upload a file'));
  generate();

  expect(screen.queryByLabelText(QUESTION)).toBeNull();
  expect(materialsApi.upload).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
});

test('switching modes keeps what was typed in the prompt', () => {
  renderForm();
  fill('Topic', 'Cells');

  fireEvent.click(radio('Upload a file'));
  fireEvent.click(radio('Write a prompt'));

  expect(screen.getByLabelText('Topic').value).toBe('Cells');
});

test('a topic the file doesnt cover shows beside the topic, not as an alert', async () => {
  const message = "That file doesn't seem to cover this topic. Try another one.";
  renderForm({ error: { status: 422, code: 'validation_error', message, field: 'topic' } });

  const input = await upToTheQuestion();

  expect(screen.getByText(message)).toBeTruthy();
  expect(input.getAttribute('aria-invalid')).toBe('true');
  expect(screen.queryByRole('alert')).toBeNull();
});

// --- busy and errors from the server ------------------------------------------------

test('while busy, Generate is disabled and the status says to wait', () => {
  renderForm({ busy: true });

  expect(generateButton().disabled).toBe(true);
  expect(screen.getByRole('status').textContent).toBe('Generating… this can take up to a minute.');
});

test('when not busy, the status is empty', () => {
  renderForm();

  expect(screen.getByRole('status').textContent).toBe('');
});

test('a rate_limited error shows its message in the alert', () => {
  const message = "You've reached the limit of 10 AI generations in 24 hours. Try again later.";
  renderForm({ error: { status: 429, code: 'rate_limited', message } });

  expect(screen.getByRole('alert').textContent).toBe(message);
});

test.each([
  ['prompt', 'Topic'],
  ['count', 'How many cards?'],
])('a server error naming %s marks that input invalid', (field, label) => {
  renderForm({ error: { status: 422, code: 'validation_error', message: 'Not valid.', field } });

  expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('true');
  expect(screen.getByRole('alert').textContent).toBe('Not valid.');
});

