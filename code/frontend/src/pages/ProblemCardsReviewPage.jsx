import { useCallback, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { createProblemCardsApi } from '../api/problemCards.js';
import { useApi } from '../api/useApi.js';
import DeckLoadError from '../components/DeckLoadError.jsx';
import { useLoad } from '../hooks/useLoad.js';
import { useSuggestions } from '../suggestions/SuggestionsContext.jsx';
import '../generate.css';
import '../problemCards.css';

const KIND_LABELS = {
  rewrite: 'Rewrite this card',
  split: 'Split it into smaller cards',
  contrast: 'Add a card that tells them apart',
  prerequisite: 'Add a background card',
};

// These kinds remove the original card. The others keep it.
const REPLACING_KINDS = new Set(['rewrite', 'split']);
const REMOVE = 'remove';

const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

/** The review page at /decks/:id/problem-cards. The view takes `api` as a prop, so tests can fake it. */
export default function ProblemCardsReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const api = useApi(createProblemCardsApi);
  const { refresh } = useSuggestions();
  return <div className="generate">
    <ProblemCardsReviewView key={id} api={api} deckId={id} onExit={() => navigate(`/decks/${id}`)}
      onApplied={refresh} />
  </div>;
}

/**
 * Shows the saved recommendations, then what changed. No AI runs on this page, and the deck
 * changes only when the learner applies their choices.
 *
 * props:
 *   api        { getDeckReview(deckId), submitDecisions(reviewId, decisions) }
 *   deckId     string, from the route
 *   onExit     () => void, back to the deck page
 *   onApplied  () => void, after the deck changes
 */
export function ProblemCardsReviewView({ api, deckId, onExit, onApplied }) {
  const load = useCallback(() => api.getDeckReview(deckId), [api, deckId]);
  const { data, error: loadError, loading, reload } = useLoad(load);

  const [choices, setChoices] = useState({});  // card id -> option index or REMOVE. Missing keeps it.
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // One request at a time, because a second click can land before React re-renders.
  const sending = useRef(false);

  const submit = async () => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    setConfirming(false);
    const decisions = data.review.recommendations.map((item) => ({
      card_id: item.card_id,
      option: choices[item.card_id] ?? null,
    }));
    try {
      setResult(await api.submitDecisions(data.review.id, decisions));
      onApplied?.();
    } catch (err) {
      // A 401 is the adapter's job: it signs out, and ProtectedRoute redirects.
      if (err.code !== 'unauthorized') setError(err);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  const apply = () => {
    if (Object.values(choices).includes(REMOVE)) setConfirming(true);
    else submit();
  };

  const choose = (cardId, choice) => {
    setChoices((current) => ({ ...current, [cardId]: choice }));
    setConfirming(false);
  };

  if (loading) {
    return <main className="page">
      <p className="page-status" role="status">Loading…</p>
    </main>;
  }

  if (loadError) {
    return <DeckLoadError title="Unable to review cards" error={loadError} onRetry={reload} onExit={onExit} />;
  }

  return <main className="page generate-page">
    <button type="button" className="text-button generate-back" onClick={onExit}>
      <span aria-hidden="true">← </span>Back to deck
    </button>
    <div className="page-heading">
      <div>
        <p className="eyebrow">Card review</p>
        <h1>Cards you keep forgetting</h1>
      </div>
    </div>

    {error && <p className="error-message" role="alert">{error.message}</p>}

    {result
      ? <Summary result={result} onExit={onExit} />
      : data.review
        ? <Recommendations review={data.review} choices={choices} busy={busy} confirming={confirming}
          onChoose={choose} onApply={apply} onConfirm={submit} onCancel={() => setConfirming(false)} />
        : <section className="panel problem-cards-section">
          <p>There are no suggestions for this deck right now.</p>
          <button type="button" className="button secondary" onClick={onExit}>Back to deck</button>
        </section>}
  </main>;
}

function Recommendations({ review, choices, busy, confirming, onChoose, onApply, onConfirm, onCancel }) {
  return <section className="problem-cards-section">
    {review.shared_cause && <p className="panel problem-cards-cause">{review.shared_cause}</p>}
    {review.verification === 'skipped'
      && <p className="candidate-note">The accuracy check didn't run on these suggestions, so read them closely.</p>}
    <p className="candidate-note">
      Nothing changes until you apply. AI can make mistakes, so check each suggestion.
    </p>
    {review.recommendations.map((item) => <fieldset key={item.card_id} className="panel problem-cards-card">
      <legend className="candidate-front">{item.front}</legend>
      <div className="problem-cards-card-meta">
        <span className="muted">Answer: {item.back}</span>
        <span className="muted">Forgotten {item.lapses} times</span>
      </div>
      {item.options.map((option, index) => <Choice key={option.kind} card={item} value={index}
        checked={choices[item.card_id] === index} busy={busy} onChoose={onChoose}>
        <strong>{KIND_LABELS[option.kind]}</strong>
        <span className="muted">{option.reason}</span>
        <ul className="problem-cards-new-cards">
          {option.cards.map((card) => <li key={card.front}>New: {card.front} → {card.back}</li>)}
        </ul>
        <span className="muted">
          {REPLACING_KINDS.has(option.kind)
            ? 'This replaces your card and starts over.'
            : 'Your card stays. New cards are added.'}
        </span>
      </Choice>)}
      <Choice card={item} value={REMOVE} checked={choices[item.card_id] === REMOVE} busy={busy}
        onChoose={onChoose}>
        <strong>Remove this card</strong>
        <span className="muted">Deletes the card and its review history.</span>
      </Choice>
      <Choice card={item} value={undefined} checked={choices[item.card_id] === undefined} busy={busy}
        onChoose={onChoose}>
        <strong>Keep it as it is</strong>
        <span className="muted">Same schedule. It comes back here after 2 more lapses.</span>
      </Choice>
    </fieldset>)}
    {confirming
      ? <div className="panel problem-cards-confirm" role="alert">
        <p><strong>Delete the cards you marked Remove?</strong> Their review history goes too.</p>
        <div className="problem-cards-notice-actions">
          <button type="button" className="button danger" disabled={busy} onClick={onConfirm}>Delete and apply</button>
          <button type="button" className="button secondary" onClick={onCancel}>Go back</button>
        </div>
      </div>
      : <button type="button" className="button primary problem-cards-action" disabled={busy} onClick={onApply}>
        {busy ? 'Applying…' : 'Apply my choices'}
      </button>}
  </section>;
}

function Choice({ card, value, checked, busy, onChoose, children }) {
  return <label className="problem-cards-option">
    <input type="radio" name={`card-${card.card_id}`} disabled={busy} checked={checked}
      onChange={() => onChoose(card.card_id, value)} />
    <span className="problem-cards-option-text">{children}</span>
  </label>;
}

function Summary({ result, onExit }) {
  const kinds = result.review.decisions.map((item) => item.kind);
  const removed = kinds.filter((kind) => kind === REMOVE).length;
  const kept = kinds.filter((kind) => kind === null).length;
  const improved = kinds.length - removed - kept;
  return <section className="panel problem-cards-section" role="status">
    <p>{plural(improved, 'card')} improved, {removed} removed, {kept} kept.</p>
    {result.cards.length > 0 && <p>{plural(result.cards.length, 'new card')} added to your deck.</p>}
    {improved === 0 && removed === 0 && <p className="muted">No new suggestions for this deck for 7 days.</p>}
    <button type="button" className="button secondary" onClick={onExit}>Back to deck</button>
  </section>;
}
