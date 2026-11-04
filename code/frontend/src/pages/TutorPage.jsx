import { useCallback, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { createTutorApi } from '../api/tutor.js';
import { useApi } from '../api/useApi.js';
import DeckLoadError from '../components/DeckLoadError.jsx';
import { useLoad } from '../hooks/useLoad.js';
import '../generate.css';
import '../tutor.css';

const QUIZ_REQUEST = 'Quiz me on my weak cards.';
const MESSAGE_MAX = 2000;

/** The tutor page at /decks/:id/tutor. The view takes `api` as a prop, so tests can fake it. */
export default function TutorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const api = useApi(createTutorApi);
  return <div className="generate">
    <TutorView key={id} api={api} deckId={id} onExit={() => navigate(`/decks/${id}`)} />
  </div>;
}

/**
 * The chat. Messages show as plain text. New cards are only added by the learner's approval.
 *
 * props:
 *   api     { getTutor(deckId), sendMessage(deckId, text), decideProposal(deckId, id, accept),
 *             resetTutor(deckId) }
 *   deckId  string, from the route
 *   onExit  () => void, back to the deck page
 */
export function TutorView({ api, deckId, onExit }) {
  const load = useCallback(() => api.getTutor(deckId), [api, deckId]);
  const { data, error: loadError, loading, reload, setData } = useLoad(load);

  const [draft, setDraft] = useState('');
  const [sentText, setSentText] = useState(null);  // shown while the reply is on its way
  const [busy, setBusy] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [error, setError] = useState(null);
  // One request at a time, because a second click can land before React re-renders.
  const sending = useRef(false);

  const run = async (request, onFailure) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      await request();
    } catch (err) {
      // A 401 is the adapter's job: it signs out, and ProtectedRoute redirects.
      if (err.code !== 'unauthorized') {
        setError(err);
        onFailure?.();
      }
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  const send = (text) => {
    const message = text.trim();
    if (!message) return;
    setSentText(message);
    setDraft('');
    run(async () => {
      setData(await api.sendMessage(deckId, message));
      setSentText(null);
    }, () => {
      // Back in the box, so nothing the learner typed is lost.
      setSentText(null);
      setDraft(message);
    });
  };

  const decide = (accept) => run(async () => {
    setData(await api.decideProposal(deckId, data.proposal.id, accept));
  });

  const reset = () => run(async () => {
    await api.resetTutor(deckId);
    setConfirmingReset(false);
    await reload();
  });

  if (loading) {
    return <main className="page">
      <p className="page-status" role="status">Loading…</p>
    </main>;
  }

  if (loadError) {
    return <DeckLoadError title="Unable to open the tutor" error={loadError} onRetry={reload} onExit={onExit} />;
  }

  const { messages, proposal, enabled } = data;
  const empty = messages.length === 0 && !sentText;

  return <main className="page generate-page">
    <button type="button" className="text-button generate-back" onClick={onExit}>
      <span aria-hidden="true">← </span>Back to deck
    </button>
    <div className="page-heading">
      <div>
        <p className="eyebrow">Deck tutor</p>
        <h1>Ask about this deck</h1>
      </div>
      {messages.length > 0 && !confirmingReset
        && <button type="button" className="button secondary" disabled={busy}
          onClick={() => setConfirmingReset(true)}>Reset chat</button>}
    </div>

    <p className="candidate-note">
      Chats are sent to Google's AI, so don't share private information. The tutor can make mistakes.
    </p>

    {confirmingReset && <div className="panel tutor-confirm" role="alert">
      <p>Delete this chat? This can't be undone.</p>
      <div className="tutor-actions">
        <button type="button" className="button secondary" disabled={busy} onClick={reset}>Delete chat</button>
        <button type="button" className="button secondary" onClick={() => setConfirmingReset(false)}>Keep it</button>
      </div>
    </div>}

    {!enabled && <p className="candidate-note">The tutor isn't available right now.</p>}

    <section className="panel tutor-chat" aria-label="Conversation">
      {empty && <p className="muted">
        Ask a question, or practice with your hardest cards. I'll give you hints first, and the
        full answer if you ask.
      </p>}
      <ul className="tutor-messages">
        {messages.map((message, index) => <li key={index}
          className={`tutor-message tutor-${message.role}${message.error ? ' tutor-error' : ''}`}>
          {message.text}
        </li>)}
        {sentText && <li className="tutor-message tutor-user">{sentText}</li>}
        {sentText && <li className="tutor-message tutor-tutor muted" role="status">Thinking…</li>}
      </ul>

      {proposal && <div className="tutor-proposal">
        <h2>Suggested cards</h2>
        {proposal.verification === 'skipped'
          && <p className="candidate-note">The accuracy check didn't run on these cards, so read them closely.</p>}
        <ul>
          {proposal.cards.map((card) => <li key={card.front}>{card.front} → {card.back}</li>)}
        </ul>
        <div className="tutor-actions">
          <button type="button" className="button primary" disabled={busy} onClick={() => decide(true)}>Add to deck</button>
          <button type="button" className="button secondary" disabled={busy} onClick={() => decide(false)}>No thanks</button>
        </div>
      </div>}
    </section>

    {error && <p className="error-message" role="alert">{error.message}</p>}

    <form className="tutor-form" onSubmit={(event) => { event.preventDefault(); send(draft); }}>
      <label className="sr-only" htmlFor="tutor-input">Your message</label>
      <textarea id="tutor-input" rows="2" maxLength={MESSAGE_MAX} value={draft}
        placeholder="Ask about this deck…" disabled={busy || Boolean(proposal) || !enabled}
        onChange={(event) => setDraft(event.target.value)} />
      <div className="tutor-actions">
        <button type="submit" className="button primary"
          disabled={busy || Boolean(proposal) || !enabled || !draft.trim()}>Send</button>
        <button type="button" className="button secondary"
          disabled={busy || Boolean(proposal) || !enabled}
          onClick={() => send(QUIZ_REQUEST)}>Quiz me</button>
      </div>
    </form>
  </main>;
}
