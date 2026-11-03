/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { useId, useState } from 'react';
import { useMaterialUpload } from '../../hooks/useMaterialUpload.js';
import FieldMessage from './FieldMessage.jsx';
import MaterialFields from './MaterialFields.jsx';

// The server's limits (C2 in code/plans/ITERATION_3_PLAN.md). Each check here mirrors one
// there, so a mistake is caught before it spends any of the free quota.
const MAX_CARDS = 25;
const TOPIC_MAX = 2000;

const MODES = [
  ['prompt', 'Write a prompt'],
  ['file', 'Upload a file'],
];

const MESSAGES = {
  count: `Choose between 1 and ${MAX_CARDS} cards.`,
  topicRequired: 'Describe what the cards should cover.',
  topicTooLong: 'Keep the topic to 2,000 characters or fewer.',
  fileRequired: 'Choose a PDF, TXT or MD file.',
  focusRequired: 'Say what you want to focus on.',
};

// C2's field names, which the server's error.field uses too, to the inputs' ids below. Only one
// of the two topic inputs is ever on the page.
const INPUT_IDS = { count: 'count', prompt: 'topic', file: 'file', topic: 'topic' };

/**
 * The generate form: a prompt or a file, and how many cards (F1).
 *
 * File mode has two steps. Generate first uploads the file, and then, once it's ready, it asks
 * what to focus on, and Generate sends that.
 *
 * Suggest something isn't a mode. It offers topics, and picking one fills in the prompt.
 *
 * props (C7):
 *   deck          a Deck, from GET /api/decks/:id
 *   busy          boolean: a generate request is running
 *   error         an ApiError from the last generate request, or null
 *   onGenerate    (body) => Promise: sends one request, with a body exactly as in C2
 *   onSuggest     () => Promise<{ topics }>: asks for topics to learn next
 *   materialsApi  a createMaterialsApi client
 */
export default function GenerateForm({ busy, error, onGenerate, onSuggest, materialsApi }) {
  const id = useId();
  const [mode, setMode] = useState('prompt');
  const [count, setCount] = useState('10');
  const [topic, setTopic] = useState('');
  const [chosenFile, setChosenFile] = useState(null);
  const [focus, setFocus] = useState('');
  const [errors, setErrors] = useState({});
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState(null); // null until the first answer
  const [suggestError, setSuggestError] = useState(null);
  const { upload, reset, uploading, material, error: uploadError } = useMaterialUpload(materialsApi);

  const materialReady = material?.status === 'ready';
  const preparing = uploading || material?.status === 'processing';
  // In file mode, the count comes with the question about the topic.
  const showCount = mode !== 'file' || materialReady;
  const topicFromServer = error?.field === 'topic' ? error.message : undefined;
  // A field is invalid when our own check failed, or when the server named it (C5).
  const invalid = (field) => Boolean(errors[field]) || error?.field === field;
  const clearError = (field) => setErrors(({ [field]: _cleared, ...rest }) => rest);

  function forgetFile() {
    reset();
    setChosenFile(null);
    setFocus('');
    clearError('file');
    clearError('topic');
  }

  function chooseMode(value) {
    setMode(value);
    // The file input exists only in file mode, and comes back empty, so the file goes with it:
    // the form never works from a file it no longer shows.
    forgetFile();
  }

  function chooseFile(file) {
    forgetFile();
    setChosenFile(file);
  }

  async function suggest() {
    setSuggesting(true);
    setSuggestions(null);
    setSuggestError(null);
    try {
      setSuggestions((await onSuggest()).topics);
    } catch (failure) {
      setSuggestError(failure);
    } finally {
      setSuggesting(false);
    }
  }

  function pickSuggestion(suggestion) {
    chooseMode('prompt');
    setTopic(suggestion);
    clearError('prompt');
    setSuggestions(null);
  }

  function showErrors(found) {
    setErrors(found);
    // Focus the first field with a problem, so a screen reader reads its message out.
    const first = ['count', 'prompt', 'file', 'topic'].find((field) => found[field]);
    if (first) document.getElementById(`${id}-${INPUT_IDS[first]}`)?.focus();
    return Boolean(first);
  }

  function submit(event) {
    event.preventDefault();
    if (busy || preparing) return;

    // A failed file stays chosen, so Generate tries it again.
    if (mode === 'file' && !materialReady) {
      if (!chosenFile) showErrors({ file: MESSAGES.fileRequired });
      else {
        setErrors({});
        upload(chosenFile);
      }
      return;
    }

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
      body.document_id = material.id;
      body.topic = focus.trim();
      if (!body.topic) found.topic = MESSAGES.focusRequired;
    }

    if (!showErrors(found)) onGenerate(body);
  }

  return <form className="generate-form" onSubmit={submit} noValidate>
    <fieldset className="generate-modes">
      <legend>Generate from</legend>
      <div className="generate-mode-options">
        {MODES.map(([value, label]) => <label key={value} className="generate-mode">
          <input type="radio" name={`${id}-mode`} value={value} checked={mode === value}
            onChange={() => chooseMode(value)} />
          <span>{label}</span>
        </label>)}
      </div>
    </fieldset>

    <div className="generate-suggest">
      <button type="button" className="button secondary" disabled={busy || suggesting}
        onClick={suggest}>Suggest something</button>
      {suggesting && <p className="field-hint">Thinking of topics…</p>}
      {suggestError && <p className="error-message" role="alert">{suggestError.message}</p>}
      {suggestions?.length === 0 && <p className="field-hint">No suggestions this time. Try again.</p>}
      {suggestions?.length > 0 && <div className="topic-chips" role="group" aria-label="Topics to learn">
        {suggestions.map((suggestion) => <button key={suggestion} type="button" className="topic-chip"
          onClick={() => pickSuggestion(suggestion)}>{suggestion}</button>)}
      </div>}
    </div>

    {showCount && <>
      <label htmlFor={`${id}-count`}>How many cards?</label>
      <input id={`${id}-count`} className="generate-count" type="number" min={1} max={MAX_CARDS}
        step={1} inputMode="numeric" value={count} aria-invalid={invalid('count')}
        aria-describedby={`${id}-count-message`}
        onChange={(event) => { setCount(event.target.value); clearError('count'); }} />
      <FieldMessage id={`${id}-count-message`} error={errors.count}>From 1 to {MAX_CARDS}.</FieldMessage>
    </>}

    {mode === 'prompt' && <>
      <label htmlFor={`${id}-topic`}>Topic</label>
      <textarea id={`${id}-topic`} rows={4} value={topic} aria-invalid={invalid('prompt')}
        aria-describedby={`${id}-topic-message`} placeholder="The bones of the human hand"
        onChange={(event) => { setTopic(event.target.value); clearError('prompt'); }} />
      <FieldMessage id={`${id}-topic-message`} error={errors.prompt}>
        {topic.length.toLocaleString()} / 2,000 characters
      </FieldMessage>
    </>}

    {mode === 'file' && <MaterialFields id={id} uploading={uploading} material={material}
      error={uploadError ?? (errors.file ? { message: errors.file } : null)}
      topic={focus} topicError={errors.topic || topicFromServer}
      onChooseFile={chooseFile}
      onTopicChange={(value) => { setFocus(value); clearError('topic'); }} />}

    {/* A topic error shows beside the topic instead. */}
    {error && !topicFromServer && <p className="error-message" role="alert">{error.message}</p>}

    <div className="form-actions">
      <button type="submit" className="button primary" disabled={busy || preparing}>Generate</button>
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
