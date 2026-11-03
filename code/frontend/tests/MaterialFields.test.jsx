// @vitest-environment jsdom

import { useState } from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import MaterialFields from '../src/components/generate/MaterialFields.jsx';

afterEach(cleanup);

const READY = {
  id: 7, filename: 'notes.pdf', status: 'ready', stage: 'finding_topics',
  chunks_done: 3, chunks_total: 3, suggested_topics: ['Mitosis', 'Enzymes'], error: null,
};
const QUESTION = 'What do you want to focus on?';

function renderFields(props = {}) {
  const onChooseFile = vi.fn();
  const onTopicChange = vi.fn();
  render(<MaterialFields id="form" uploading={false} material={null} error={null} topic=""
    onChooseFile={onChooseFile} onTopicChange={onTopicChange} {...props} />);
  return { onChooseFile, onTopicChange };
}

const fileInput = () => screen.getByLabelText('File');

function choose(name, size = 10) {
  const file = new File(['x'], name);
  Object.defineProperty(file, 'size', { value: size });
  fireEvent.change(fileInput(), { target: { files: [file] } });
  return file;
}

test('before a file is chosen, only the file field shows', () => {
  renderFields();

  expect(screen.getByText('PDF, TXT or MD, up to 50 MB.')).toBeTruthy();
  expect(screen.queryByLabelText(QUESTION)).toBeNull();
  expect(screen.getByRole('status').textContent).toBe('');
});

test.each(['notes.pdf', 'notes.TXT', 'notes.md'])('%s is accepted', (name) => {
  const { onChooseFile } = renderFields();

  const file = choose(name);

  expect(onChooseFile).toHaveBeenCalledWith(file);
  expect(screen.queryByText(/Only PDF/)).toBeNull();
});

test('an unsupported file is refused with a message', () => {
  const { onChooseFile } = renderFields();

  choose('photo.png');

  expect(onChooseFile).toHaveBeenCalledWith(null);
  expect(screen.getByText(/Only PDF, TXT and MD/)).toBeTruthy();
  expect(fileInput().getAttribute('aria-invalid')).toBe('true');
});

test('a file over 50 MB is refused with a message', () => {
  const { onChooseFile } = renderFields();

  choose('huge.pdf', 50 * 1024 * 1024 + 1);

  expect(onChooseFile).toHaveBeenCalledWith(null);
  expect(screen.getByText('The file must be 50 MB or smaller.')).toBeTruthy();
});

test('choosing a good file clears an earlier refusal', () => {
  renderFields();

  choose('photo.png');
  choose('notes.pdf');

  expect(screen.queryByText(/Only PDF/)).toBeNull();
});

test('while uploading, the file field is locked and says so', () => {
  renderFields({ uploading: true });

  expect(fileInput().disabled).toBe(true);
  expect(screen.getByRole('status').textContent).toBe('Uploading your file…');
});

test('while embedding, a progress bar shows the count, outside the status text', () => {
  renderFields({
    material: { ...READY, status: 'processing', stage: 'embedding', chunks_done: 300, chunks_total: 1000 },
  });

  const bar = screen.getByRole('progressbar', { name: 'Saving your materials' });
  expect(bar.getAttribute('value')).toBe('300');
  expect(bar.getAttribute('max')).toBe('1000');
  expect(screen.getByRole('status').textContent).toBe('Saving your materials…');
  expect(fileInput().disabled).toBe(true);
  expect(screen.queryByLabelText(QUESTION)).toBeNull();
});

test('other stages show no progress bar', () => {
  renderFields({ material: { ...READY, status: 'processing', stage: 'reading' } });

  expect(screen.queryByRole('progressbar')).toBeNull();
});

test('a failed document shows its message and lets another file be chosen', () => {
  renderFields({ material: { ...READY, status: 'failed', error: "That file couldn't be read." } });

  expect(screen.getByText("That file couldn't be read.")).toBeTruthy();
  expect(fileInput().disabled).toBe(false);
  expect(screen.queryByLabelText(QUESTION)).toBeNull();
});

test('a refused upload shows the server message', () => {
  renderFields({ error: new Error("You've reached the limit of 10 new files in 24 hours.") });

  expect(screen.getByText(/limit of 10 new files/)).toBeTruthy();
});

test('when ready, the question appears, takes focus, and names the file', () => {
  renderFields({ material: READY });

  const input = screen.getByLabelText(QUESTION);
  expect(globalThis.document.activeElement).toBe(input);
  expect(screen.getByText('Cards come only from notes.pdf.')).toBeTruthy();
  expect(fileInput().disabled).toBe(false);
});

test('a suggested topic fills the box, and shows as chosen', () => {
  function Controlled() {
    const [topic, setTopic] = useState('');
    return <MaterialFields id="form" uploading={false} material={READY} error={null} topic={topic}
      onChooseFile={() => {}} onTopicChange={setTopic} />;
  }
  render(<Controlled />);
  const chip = screen.getByRole('button', { name: 'Mitosis' });
  expect(chip.getAttribute('aria-pressed')).toBe('false');

  fireEvent.click(chip);

  expect(screen.getByLabelText(QUESTION).value).toBe('Mitosis');
  expect(chip.getAttribute('aria-pressed')).toBe('true');
});

test('a suggested topic doesnt submit the form', () => {
  const onSubmit = vi.fn((event) => event.preventDefault());
  render(<form onSubmit={onSubmit}>
    <MaterialFields id="form" uploading={false} material={READY} error={null} topic=""
      onChooseFile={() => {}} onTopicChange={() => {}} />
  </form>);

  fireEvent.click(screen.getByRole('button', { name: 'Enzymes' }));

  expect(onSubmit).not.toHaveBeenCalled();
});

test('typing a topic reports the text', () => {
  const { onTopicChange } = renderFields({ material: READY });

  fireEvent.change(screen.getByLabelText(QUESTION), { target: { value: 'Cell cycle' } });

  expect(onTopicChange).toHaveBeenCalledWith('Cell cycle');
});

test('with no suggestions, the question still works', () => {
  renderFields({ material: { ...READY, suggested_topics: [] } });

  expect(screen.getByLabelText(QUESTION)).toBeTruthy();
  expect(screen.queryByRole('group')).toBeNull();
});

test('the form can show its own topic error', () => {
  renderFields({ material: READY, topicError: 'Say what you want to focus on.' });

  expect(screen.getByText('Say what you want to focus on.')).toBeTruthy();
  expect(screen.getByLabelText(QUESTION).getAttribute('aria-invalid')).toBe('true');
});
