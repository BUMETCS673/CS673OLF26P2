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
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import GenerateForm from '../src/components/generate/GenerateForm.jsx';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DECK = { id: 2, name: 'Travel Spanish', description: null, card_count: 12 };
const UNSUPPORTED = 'Only PDF, TXT and MD files are supported. Save other documents as a PDF first.';
const COUNT_RANGE = 'Choose between 1 and 25 cards.';
const PRIVACY = "Your prompt or file is sent to Google Gemini. Don't include personal or confidential information.";

function renderForm(props = {}) {
  const onGenerate = vi.fn().mockResolvedValue(undefined);
  render(<GenerateForm deck={DECK} cardCount={12} busy={false} error={null} onGenerate={onGenerate} {...props} />);
  return { onGenerate: props.onGenerate ?? onGenerate };
}

const radio = (name) => screen.getByRole('radio', { name });
const generateButton = () => screen.getByRole('button', { name: 'Generate' });
const generate = () => fireEvent.click(generateButton());
const fill = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const textFile = (text, name, type = '') => new File([text], name, { type });

/** Chooses `file` in file mode, and waits for the read to finish. */
async function chooseFile(file) {
  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [file] } });
  await waitFor(() => expect(generateButton().disabled).toBe(false));
}

// --- the form as it first appears ----------------------------------------------------

test('it starts on Write a prompt, with three modes, 10 cards and a Topic box', () => {
  renderForm();

  const group = screen.getByRole('group', { name: 'Generate from' });
  expect(group).toBeTruthy();
  expect(radio('Suggest more content').checked).toBe(false);
  expect(radio('Write a prompt').checked).toBe(true);
  expect(radio('Upload a file').checked).toBe(false);
  expect(screen.getByLabelText('How many cards?').value).toBe('10');
  expect(screen.getByLabelText('Topic')).toBeTruthy();
  expect(screen.queryByLabelText('File')).toBeNull();
});

test('the privacy line shows in every mode', () => {
  renderForm();

  for (const mode of ['Write a prompt', 'Upload a file', 'Suggest more content']) {
    fireEvent.click(radio(mode));
    expect(screen.getByText(PRIVACY)).toBeTruthy();
  }
});

// --- Suggest more content -------------------------------------------------------------

test('with 4 cards, Suggest more content is disabled and says how many more it needs', () => {
  renderForm({ cardCount: 4 });

  expect(radio('Suggest more content').disabled).toBe(true);
  expect(screen.getByText('Add 6 more cards to unlock suggestions.')).toBeTruthy();
});

test('with 9 cards, it needs 1 more card', () => {
  renderForm({ cardCount: 9 });

  expect(screen.getByText('Add 1 more card to unlock suggestions.')).toBeTruthy();
});

test('with 10 cards, Suggest more content is enabled and the hint goes', () => {
  renderForm({ cardCount: 10 });

  expect(radio('Suggest more content').disabled).toBe(false);
  expect(screen.queryByText(/to unlock suggestions/)).toBeNull();
});

test('with 12 cards, Suggest sends the mode and the count, and nothing else', () => {
  const { onGenerate } = renderForm({ cardCount: 12 });
  fill('Topic', 'Left over from prompt mode');

  fireEvent.click(radio('Suggest more content'));
  fill('How many cards?', '5');
  generate();

  expect(screen.queryByLabelText('Topic')).toBeNull();
  expect(onGenerate).toHaveBeenCalledTimes(1);
  expect(onGenerate).toHaveBeenCalledWith({ mode: 'suggest', count: 5 });
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

test('Upload a file shows a File input and a Focus box, and no Topic', () => {
  renderForm();

  fireEvent.click(radio('Upload a file'));

  expect(screen.getByLabelText('File').getAttribute('accept')).toBe('.pdf,.txt,.md');
  expect(screen.getByLabelText('Focus (optional)')).toBeTruthy();
  expect(screen.queryByLabelText('Topic')).toBeNull();
});

test('an .md file is read and sent as base64, with its type and no focus', async () => {
  const { onGenerate } = renderForm();
  fill('Topic', 'Left over from prompt mode');

  await chooseFile(textFile('# Hi', 'notes.md'));
  generate();

  expect(onGenerate).toHaveBeenCalledTimes(1);
  expect(onGenerate).toHaveBeenCalledWith({
    mode: 'file',
    count: 10,
    file: { name: 'notes.md', mime_type: 'text/markdown', data: 'IyBIaQ==' },
  });
});

test('the type comes from the extension, never from what the browser says', async () => {
  const { onGenerate } = renderForm();

  // A browser may call .md text/x-markdown, or leave the type empty.
  await chooseFile(textFile('%PDF-1.7', 'Chapter 2.PDF', 'text/x-markdown'));
  generate();

  expect(onGenerate.mock.calls[0][0].file).toEqual({
    name: 'Chapter 2.PDF', mime_type: 'application/pdf', data: btoa('%PDF-1.7'),
  });
});

test('a .txt file is text/plain, and a focus note is sent trimmed', async () => {
  const { onGenerate } = renderForm();

  await chooseFile(textFile('Mitochondria', 'cells.txt'));
  fill('Focus (optional)', '  Chapter 2 only  ');
  generate();

  expect(onGenerate).toHaveBeenCalledWith({
    mode: 'file',
    count: 10,
    file: { name: 'cells.txt', mime_type: 'text/plain', data: btoa('Mitochondria') },
    focus: 'Chapter 2 only',
  });
});

test('file mode with no file is caught', () => {
  const { onGenerate } = renderForm();

  fireEvent.click(radio('Upload a file'));
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
  expect(screen.getByLabelText('File').getAttribute('aria-invalid')).toBe('true');
});

test('a file over 4 MB is refused before it is read, and Generate sends nothing', async () => {
  const read = vi.spyOn(globalThis.FileReader.prototype, 'readAsDataURL');
  const { onGenerate } = renderForm();
  const big = new File([new Uint8Array(4 * 1024 * 1024 + 1)], 'big.pdf', { type: 'application/pdf' });

  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [big] } });
  generate();

  expect(read).not.toHaveBeenCalled();
  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('The file must be 4 MB or smaller.')).toBeTruthy();
});

test('a file of exactly 4 MB is accepted', async () => {
  const { onGenerate } = renderForm();

  await chooseFile(new File([new Uint8Array(4 * 1024 * 1024)], 'max.pdf'));
  generate();

  expect(onGenerate).toHaveBeenCalledTimes(1);
});

test('a .docx is refused with C2\'s message', () => {
  const { onGenerate } = renderForm();

  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [textFile('x', 'report.docx')] } });

  expect(screen.getByText(UNSUPPORTED)).toBeTruthy();
  generate();
  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText(UNSUPPORTED)).toBeTruthy();
});

test('a refused file replaces a good one', async () => {
  const { onGenerate } = renderForm();
  await chooseFile(textFile('# Hi', 'notes.md'));

  fireEvent.change(screen.getByLabelText('File'), { target: { files: [textFile('x', 'notes')] } });
  generate();

  expect(screen.getByText(UNSUPPORTED)).toBeTruthy();
  expect(onGenerate).not.toHaveBeenCalled();
});

test('a focus note over 500 characters is caught', async () => {
  const { onGenerate } = renderForm();
  await chooseFile(textFile('# Hi', 'notes.md'));

  fill('Focus (optional)', 'x'.repeat(501));
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Keep the focus note to 500 characters or fewer.')).toBeTruthy();
});

test('Generate waits while a file is being read', () => {
  vi.spyOn(globalThis.FileReader.prototype, 'readAsDataURL').mockImplementation(() => {});
  const { onGenerate } = renderForm();

  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [textFile('# Hi', 'notes.md')] } });

  expect(generateButton().disabled).toBe(true);
  expect(screen.getByText('Reading notes.md…')).toBeTruthy();
  fireEvent.submit(generateButton().closest('form'));
  expect(onGenerate).not.toHaveBeenCalled();
});

test('a file that cannot be read says so', async () => {
  vi.spyOn(globalThis.FileReader.prototype, 'readAsDataURL').mockImplementation(function fail() {
    setTimeout(() => this.onerror(new globalThis.ProgressEvent('error')));
  });
  renderForm();

  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [textFile('# Hi', 'notes.md')] } });

  expect(await screen.findByText("That file couldn't be read.")).toBeTruthy();
  expect(generateButton().disabled).toBe(false);
});

test('a slow read never replaces a file chosen after it', () => {
  const held = [];
  vi.spyOn(globalThis.FileReader.prototype, 'readAsDataURL').mockImplementation(function hold() {
    held.push(this);
  });
  /** Finishes a held read with `base64` as its data. */
  const finish = (reader, base64) => act(() => {
    Object.defineProperty(reader, 'result', { value: `data:text/markdown;base64,${base64}` });
    reader.onload();
  });
  const { onGenerate } = renderForm();
  fireEvent.click(radio('Upload a file'));
  const input = screen.getByLabelText('File');

  fireEvent.change(input, { target: { files: [textFile('old', 'old.md')] } });
  fireEvent.change(input, { target: { files: [textFile('new', 'new.md')] } });
  finish(held[1], btoa('new'));
  finish(held[0], btoa('old'));
  generate();

  expect(onGenerate.mock.calls[0][0].file).toEqual({
    name: 'new.md', mime_type: 'text/markdown', data: btoa('new'),
  });
});

test('choosing no file after a good one leaves no file', async () => {
  const { onGenerate } = renderForm();
  await chooseFile(textFile('# Hi', 'notes.md'));

  fireEvent.change(screen.getByLabelText('File'), { target: { files: [] } });
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
});

test('switching modes keeps what was typed', () => {
  renderForm();
  fill('Topic', 'Cells');

  fireEvent.click(radio('Upload a file'));
  fireEvent.click(radio('Write a prompt'));

  expect(screen.getByLabelText('Topic').value).toBe('Cells');
});

test('a file chosen before switching modes is not sent, since the input comes back empty', async () => {
  const { onGenerate } = renderForm();
  await chooseFile(textFile('# Hi', 'notes.md'));

  fireEvent.click(radio('Write a prompt'));
  fireEvent.click(radio('Upload a file'));
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
});

test('a read still running when the mode changes is dropped', () => {
  const held = [];
  vi.spyOn(globalThis.FileReader.prototype, 'readAsDataURL').mockImplementation(function hold() {
    held.push(this);
  });
  const { onGenerate } = renderForm();
  fireEvent.click(radio('Upload a file'));
  fireEvent.change(screen.getByLabelText('File'), { target: { files: [textFile('# Hi', 'notes.md')] } });

  fireEvent.click(radio('Write a prompt'));
  expect(generateButton().disabled).toBe(false);
  fireEvent.click(radio('Upload a file'));
  act(() => {
    Object.defineProperty(held[0], 'result', { value: `data:text/markdown;base64,${btoa('# Hi')}` });
    held[0].onload();
  });
  generate();

  expect(onGenerate).not.toHaveBeenCalled();
  expect(screen.getByText('Choose a PDF, TXT or MD file.')).toBeTruthy();
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
  ['prompt', 'Write a prompt', 'Topic'],
  ['count', 'Write a prompt', 'How many cards?'],
  ['file', 'Upload a file', 'File'],
  ['focus', 'Upload a file', 'Focus (optional)'],
])('a server error naming %s marks that input invalid', (field, mode, label) => {
  renderForm({ error: { status: 422, code: 'validation_error', message: 'Not valid.', field } });

  fireEvent.click(radio(mode));

  expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('true');
  expect(screen.getByRole('alert').textContent).toBe('Not valid.');
});
