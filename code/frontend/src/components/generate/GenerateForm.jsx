/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { useId, useRef, useState } from 'react';

// The server's limits (C2 in code/plans/ITERATION_3_PLAN.md). Each check here mirrors one
// there, so a mistake is caught before it spends any of the free quota.
const MAX_CARDS = 25;
const SUGGEST_MIN_CARDS = 10;
const TOPIC_MAX = 2000;
const FOCUS_MAX = 500;
const FILE_MAX_BYTES = 4 * 1024 * 1024;

// By extension, never `file.type`, which browsers fill in differently for .md.
const MIME_TYPES = { pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown' };

const MODES = [
  ['suggest', 'Suggest more content'],
  ['prompt', 'Write a prompt'],
  ['file', 'Upload a file'],
];

const MESSAGES = {
  count: `Choose between 1 and ${MAX_CARDS} cards.`,
  topicRequired: 'Describe what the cards should cover.',
  topicTooLong: 'Keep the topic to 2,000 characters or fewer.',
  fileRequired: 'Choose a PDF, TXT or MD file.',
  unsupported: 'Only PDF, TXT and MD files are supported. Save other documents as a PDF first.',
  tooBig: 'The file must be 4 MB or smaller.',
  unreadable: "That file couldn't be read.",
  focusTooLong: 'Keep the focus note to 500 characters or fewer.',
};

// C2's field names, which the server's error.field uses too, to the inputs' ids below.
const INPUT_IDS = { count: 'count', prompt: 'topic', file: 'file', focus: 'focus' };

/** "pdf" for "Chapter 2.PDF"; "" when there's no extension. */
function extension(name) {
  const dot = name.lastIndexOf('.');
  return dot === -1 ? '' : name.slice(dot + 1).toLowerCase();
}

/**
 * The generate form: three ways to ask for cards, and how many (F1).
 *
 * props (C7):
 *   deck        a Deck, from GET /api/decks/:id
 *   cardCount   number: the deck's card_count. Suggest more content needs 10 or more
 *   busy        boolean: a generate request is running
 *   error       an ApiError from the last generate request, or null
 *   onGenerate  (body) => Promise: sends one request, with a body exactly as in C2
 */
export default function GenerateForm({ cardCount, busy, error, onGenerate }) {
  const id = useId();
  const [mode, setMode] = useState('prompt');
  const [count, setCount] = useState('10');
  const [topic, setTopic] = useState('');
  const [focus, setFocus] = useState('');
  // { name, mime_type, data } once a file has been read; `reading` holds its name meanwhile.
  const [file, setFile] = useState(null);
  const [reading, setReading] = useState(null);
  const [errors, setErrors] = useState({});
  // Each choice of file gets a number, so a slow read can't overwrite a later choice.
  const latestChoice = useRef(0);

  const suggestLocked = cardCount < SUGGEST_MIN_CARDS;
  const needed = SUGGEST_MIN_CARDS - cardCount;
  // A field is invalid when our own check failed, or when the server named it (C5).
  const invalid = (field) => Boolean(errors[field]) || error?.field === field;
  const setError = (field, message) => setErrors((current) => ({ ...current, [field]: message }));
  const clearError = (field) => setErrors(({ [field]: _cleared, ...rest }) => rest);

  function chooseFile(event) {
    const chosen = event.target.files?.[0];
    const choice = ++latestChoice.current;
    setFile(null);
    setReading(null);
    clearError('file');
    if (!chosen) return;

    const mimeType = MIME_TYPES[extension(chosen.name)];
    const refusal = !mimeType ? MESSAGES.unsupported
      : chosen.size > FILE_MAX_BYTES ? MESSAGES.tooBig : null;
    if (refusal) {
      // Clear the input too, so it doesn't go on showing a file that won't be sent.
      event.target.value = '';
      setError('file', refusal);
      return;
    }

    setReading(chosen.name);
    const reader = new FileReader();
    reader.onload = () => {
      if (choice !== latestChoice.current) return;
      setReading(null);
      // A data URL is "data:<type>;base64,<data>". The server wants only the data.
      const url = String(reader.result);
      setFile({ name: chosen.name, mime_type: mimeType, data: url.slice(url.indexOf(',') + 1) });
    };
    reader.onerror = () => {
      if (choice !== latestChoice.current) return;
      setReading(null);
      setError('file', MESSAGES.unreadable);
    };
    reader.readAsDataURL(chosen);
  }

  function submit(event) {
    event.preventDefault();
    if (busy || reading) return;

    const found = {};
    const number = Number(count);
    if (!count.trim() || !Number.isInteger(number) || number < 1 || number > MAX_CARDS) {
      found.count = MESSAGES.count;
    }
    // Only the chosen mode's fields go in the body (C2).
    const body = { mode, count: number };
    if (mode === 'prompt') {
      body.prompt = topic.trim();
      if (!body.prompt) found.prompt = MESSAGES.topicRequired;
      else if (body.prompt.length > TOPIC_MAX) found.prompt = MESSAGES.topicTooLong;
    } else if (mode === 'file') {
      body.file = file;
      // A refused or unreadable file keeps its own, more useful, message.
      if (!file) found.file = errors.file || MESSAGES.fileRequired;
      const note = focus.trim();
      if (note.length > FOCUS_MAX) found.focus = MESSAGES.focusTooLong;
      else if (note) body.focus = note;
    }

    setErrors(found);
    // Focus the first field with a problem, so a screen reader reads its message out.
    const first = ['count', 'prompt', 'file', 'focus'].find((field) => found[field]);
    if (first) document.getElementById(`${id}-${INPUT_IDS[first]}`)?.focus();
    else onGenerate(body);
  }

  return <form className="generate-form" onSubmit={submit} noValidate>
    <fieldset className="generate-modes" aria-describedby={suggestLocked ? `${id}-suggest` : undefined}>
      <legend>Generate from</legend>
      <div className="generate-mode-options">
        {MODES.map(([value, label]) => <label key={value} className="generate-mode">
          <input type="radio" name={`${id}-mode`} value={value} checked={mode === value}
            disabled={value === 'suggest' && suggestLocked} onChange={() => setMode(value)} />
          <span>{label}</span>
        </label>)}
      </div>
      {suggestLocked && <p id={`${id}-suggest`} className="field-hint">
        Add {needed} more {needed === 1 ? 'card' : 'cards'} to unlock suggestions.
      </p>}
    </fieldset>

    <label htmlFor={`${id}-count`}>How many cards?</label>
    <input id={`${id}-count`} className="generate-count" type="number" min={1} max={MAX_CARDS}
      step={1} inputMode="numeric" value={count} aria-invalid={invalid('count')}
      aria-describedby={`${id}-count-message`}
      onChange={(event) => { setCount(event.target.value); clearError('count'); }} />
    <FieldMessage id={`${id}-count-message`} error={errors.count}>From 1 to {MAX_CARDS}.</FieldMessage>

    {mode === 'prompt' && <>
      <label htmlFor={`${id}-topic`}>Topic</label>
      <textarea id={`${id}-topic`} rows={4} value={topic} aria-invalid={invalid('prompt')}
        aria-describedby={`${id}-topic-message`} placeholder="The bones of the human hand"
        onChange={(event) => { setTopic(event.target.value); clearError('prompt'); }} />
      <FieldMessage id={`${id}-topic-message`} error={errors.prompt}>
        {topic.length.toLocaleString()} / 2,000 characters
      </FieldMessage>
    </>}

    {mode === 'file' && <>
      <label htmlFor={`${id}-file`}>File</label>
      <input id={`${id}-file`} type="file" accept=".pdf,.txt,.md" aria-invalid={invalid('file')}
        aria-describedby={`${id}-file-message`} onChange={chooseFile} />
      <FieldMessage id={`${id}-file-message`} error={errors.file}>
        {reading ? `Reading ${reading}…` : 'PDF, TXT or MD, up to 4 MB.'}
      </FieldMessage>

      <label htmlFor={`${id}-focus`}>Focus <span className="optional">(optional)</span></label>
      <textarea id={`${id}-focus`} rows={2} value={focus} aria-invalid={invalid('focus')}
        aria-describedby={`${id}-focus-message`} placeholder="Chapter 2 only"
        onChange={(event) => { setFocus(event.target.value); clearError('focus'); }} />
      <FieldMessage id={`${id}-focus-message`} error={errors.focus}>
        {focus.length.toLocaleString()} / 500 characters
      </FieldMessage>
    </>}

    {error && <p className="error-message" role="alert">{error.message}</p>}

    <div className="form-actions">
      <button type="submit" className="button primary" disabled={busy || Boolean(reading)}>Generate</button>
    </div>
    {/* Always in the page, so screen readers announce the text when it appears. */}
    <p className="generate-status" role="status">
      {busy ? 'Generating… this can take up to a minute.' : ''}
    </p>

    <p className="field-hint generate-privacy">
      Your prompt or file is sent to Google Gemini. Don't include personal or confidential information.
    </p>
  </form>;
}

/** The hint under a field, or its error in place of the hint. */
function FieldMessage({ id, error, children }) {
  return <p id={id} className={error ? 'field-error' : 'field-hint'}>{error || children}</p>;
}
