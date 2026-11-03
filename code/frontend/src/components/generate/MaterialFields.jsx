import { useEffect, useRef, useState } from 'react';
import { progressMessage } from '../../hooks/useMaterialUpload.js';
import FieldMessage from './FieldMessage.jsx';

// The server's limits, checked here too so a refused file doesn't have to upload first.
const FILE_MAX_BYTES = 50 * 1024 * 1024;
export const TOPIC_MAX = 500;
// By extension, never `file.type`, which browsers fill in differently for .md.
const EXTENSIONS = /\.(pdf|txt|md)$/i;

const UNSUPPORTED = 'Only PDF, TXT and MD files are supported. Save other documents as a PDF first.';
const TOO_BIG = 'The file must be 50 MB or smaller.';

/**
 * File mode's fields: choose a file, watch it process, then say what to focus on.
 *
 * Controlled, so the form owns the submit. props:
 *   id             the form's id prefix
 *   uploading      from useMaterialUpload
 *   material       from useMaterialUpload: a Document, or null
 *   error          from useMaterialUpload: an ApiError, or null
 *   topic          the text in the topic box
 *   topicError     the form's message for the topic, or undefined
 *   onChooseFile   (File | null) => void. Null means there's no usable file.
 *   onTopicChange  (string) => void
 */
export default function MaterialFields({
  id, uploading, material, error, topic, topicError, onChooseFile, onTopicChange,
}) {
  const [refusal, setRefusal] = useState(null);
  const topicInput = useRef(null);
  const processing = material?.status === 'processing';
  const ready = material?.status === 'ready';
  const embedding = processing && material.stage === 'embedding' && material.chunks_total > 0;
  const fileError = refusal || error?.message || material?.error;

  // The question appears on its own after a wait, so take the learner straight to it.
  useEffect(() => {
    if (ready) topicInput.current?.focus();
  }, [ready]);

  function chooseFile(event) {
    const chosen = event.target.files?.[0] ?? null;
    const refused = !chosen ? null
      : !EXTENSIONS.test(chosen.name) ? UNSUPPORTED
        : chosen.size > FILE_MAX_BYTES ? TOO_BIG : null;
    setRefusal(refused);
    if (refused) event.target.value = ''; // so it doesn't go on showing a file that won't be sent
    onChooseFile(refused ? null : chosen);
  }

  return <>
    <label htmlFor={`${id}-file`}>File</label>
    <input id={`${id}-file`} type="file" accept=".pdf,.txt,.md" disabled={uploading || processing}
      aria-invalid={Boolean(fileError)} aria-describedby={`${id}-file-message`} onChange={chooseFile} />
    <FieldMessage id={`${id}-file-message`} error={fileError}>PDF, TXT or MD, up to 50 MB.</FieldMessage>

    {/* Always in the page, so screen readers announce the text when it appears. */}
    <p className="generate-status" role="status">{progressMessage(uploading, material)}</p>
    {embedding && <progress className="material-progress" aria-label="Saving your materials"
      value={material.chunks_done} max={material.chunks_total} />}

    {ready && <>
      <label htmlFor={`${id}-topic`}>What do you want to focus on?</label>
      <input ref={topicInput} id={`${id}-topic`} type="text" value={topic} maxLength={TOPIC_MAX}
        aria-invalid={Boolean(topicError)} aria-describedby={`${id}-topic-message`}
        placeholder="Type a topic, or pick one below"
        onChange={(event) => onTopicChange(event.target.value)} />
      <FieldMessage id={`${id}-topic-message`} error={topicError}>
        Cards come only from {material.filename}.
      </FieldMessage>

      {material.suggested_topics.length > 0 && <div className="topic-chips" role="group"
        aria-label="Suggested topics">
        {material.suggested_topics.map((suggestion) => <button key={suggestion} type="button"
          className="topic-chip" aria-pressed={topic === suggestion}
          onClick={() => onTopicChange(suggestion)}>{suggestion}</button>)}
      </div>}
    </>}
  </>;
}
