/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI page development
 *   Documentation
 * Human role: requirements (F1 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Duc Anh Nguyen.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useDecksApi } from '../api/useDecksApi';
import { useStudyApi } from '../api/useStudyApi';
import RatingButtons from '../components/study/RatingButtons.jsx';
import SessionSummary from '../components/study/SessionSummary.jsx';
import StudyCard from '../components/study/StudyCard.jsx';
import { RATINGS } from '../study/constants.js';
import { initSession, sessionReducer } from '../study/session.js';
import '../study.css';

/**
 * The study page at /decks/:id/study (Iteration 2, F1).
 *
 * The wrapper reads the route and the hooks, and StudyView takes everything as props, so
 * a test can render it with a fake `api` and a fixed clock (rule 12 in
 * code/plans/FINALIZE_ITERATION_2_PLAN.md).
 */
export default function StudyPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const decksApi = useDecksApi();
  const studyApi = useStudyApi();
  // Both hooks memoize on the session, so this only changes when the session does.
  const api = useMemo(() => ({ getDeck: decksApi.getDeck, ...studyApi }), [decksApi, studyApi]);
  // key={id}: a different deck mounts a fresh view, as on DeckDetailPage.
  return <div className="study">
    <StudyView key={id} api={api} deckId={id} onExit={() => navigate(`/decks/${id}`)} />
  </div>;
}

/**
 * Loads the deck and its due cards, then hands them to a StudySession.
 *
 * props:
 *   api     { getDeck(deckId), getDueCards(deckId), reviewCard(cardId, rating) }
 *   deckId  string, from the route
 *   onExit  () => void, back to the deck page
 *   now     () => number, in milliseconds. Defaults to Date.now; tests pass a fixed clock.
 */
export function StudyView({ api, deckId, onExit, now = Date.now }) {
  // Each load has a number. Try again and Study more both bump it, which fetches again,
  // and the session is keyed on it, so Study more mounts a new session with a fresh
  // reducer instead of needing a "restart" action.
  const [load, setLoad] = useState(0);
  // The result is tagged with the load it answers, so "loading" is derived rather than
  // switched on at the top of the effect (as in DeckListPage).
  const [result, setResult] = useState({ key: null, deck: null, due: null, error: null });
  const loading = result.key !== load;
  const { deck, due, error } = result;
  const reload = useCallback(() => setLoad((count) => count + 1), []);

  useEffect(() => {
    let active = true;
    Promise.all([api.getDeck(deckId), api.getDueCards(deckId)])
      .then(([nextDeck, nextDue]) => {
        if (active) setResult({ key: load, deck: nextDeck, due: nextDue, error: null });
      })
      .catch((err) => {
        if (active) setResult({ key: load, deck: null, due: null, error: err });
      });
    return () => { active = false; };
  }, [api, deckId, load]);

  if (loading) {
    return <main className="page">
      <p className="page-status" role="status">Loading…</p>
    </main>;
  }

  if (error) {
    const notFound = error.code === 'not_found';
    return <main className="page">
      <section className="state-panel">
        <h1>Unable to study this deck</h1>
        <p className="error-message" role="alert">
          {notFound ? 'This deck could not be found.' : error.message || 'Could not load this deck.'}
        </p>
        <div className="form-actions">
          {!notFound && <button type="button" className="button primary" onClick={reload}>Try again</button>}
          <button type="button" className="button secondary" onClick={onExit}>Back to deck</button>
        </div>
      </section>
    </main>;
  }

  return <StudySession key={load} api={api} deck={deck} due={due} now={now}
    onExit={onExit} onStudyMore={reload} />;
}

/** The ignored targets for the keyboard shortcuts: anywhere the learner is typing. */
const isTyping = (target) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName)
  || Boolean(target?.isContentEditable);

/** One session over `due`, from the first card to the summary. */
function StudySession({ api, deck, due, now, onExit, onStudyMore }) {
  const [state, dispatch] = useReducer(sessionReducer, { due, now: now() }, initSession);
  // Rule 11: one review request per card shown. The ref holds the session state the request
  // was sent from, so a second click or key press made from that same state does nothing.
  // A flag isn't enough: it would clear before React re-renders and re-attaches the
  // keydown listener, and the stale listener would rate the answered card again.
  const sentFrom = useRef(null);
  const [saving, setSaving] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const { current, revealed } = state;

  const reveal = useCallback(() => dispatch({ type: 'reveal' }), []);

  const rate = useCallback(async (rating) => {
    if (sentFrom.current === state || !current || !revealed) return;
    sentFrom.current = state;
    setSaving(true);
    setReviewError('');
    try {
      const card = await api.reviewCard(current.id, rating);
      dispatch({ type: 'answered', rating, card, now: now() });
    } catch (err) {
      // See "How the study page handles each review response" in the plan.
      if (err.code === 'conflict' || err.code === 'not_found') {
        dispatch({ type: 'skipped', now: now() });
      } else {
        // Nothing was saved, so the same card can be rated again.
        sentFrom.current = null;
        // A 401 is the adapter's job: it signs out, and ProtectedRoute redirects.
        if (err.code !== 'unauthorized') {
          setReviewError(err.message || 'Could not save your answer. Try again.');
        }
      }
    } finally {
      setSaving(false);
    }
  }, [api, now, state, current, revealed]);

  // Space reveals, and 1-4 rate once the answer is showing (decision P10).
  useEffect(() => {
    if (state.finished) return undefined;
    function onKeyDown(event) {
      if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTyping(event.target)) return;
      if (event.key === ' ') {
        // A focused button handles Space itself; doing it here as well would act twice.
        if (event.target?.tagName === 'BUTTON' || revealed) return;
        event.preventDefault();
        reveal();
        return;
      }
      // Digits are taken even from a focused button, which does nothing with them.
      const index = ['1', '2', '3', '4'].indexOf(event.key);
      if (index !== -1 && revealed) {
        event.preventDefault();
        rate(RATINGS[index]);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [state.finished, revealed, reveal, rate]);

  if (state.finished) {
    return <main className="page study-session">
      <p className="eyebrow">{deck.name}</p>
      <SessionSummary counts={state.counts} nextLearningDue={state.nextLearningDue} now={now()}
        onStudyMore={onStudyMore} onExit={onExit} />
    </main>;
  }

  const left = state.main.length + state.learning.length + (current ? 1 : 0);
  return <main className="page study-session">
    <div className="study-heading">
      <div>
        <p className="eyebrow">Study</p>
        <h1>{deck.name}</h1>
      </div>
      <p className="study-left">{left} {left === 1 ? 'card' : 'cards'} left</p>
    </div>

    <StudyCard card={current} revealed={revealed} />

    <div className="study-actions">
      {revealed
        ? <RatingButtons intervals={current.intervals} disabled={saving} onRate={rate} />
        : <button type="button" className="button primary study-reveal" onClick={reveal}>Show answer</button>}
      {reviewError && <p className="error-message" role="alert">{reviewError}</p>}
      <p className="study-hint">{revealed ? 'Press 1–4 to rate' : 'Press Space to show the answer'}</p>
    </div>

    <button type="button" className="text-button study-exit" onClick={onExit}>
      <span aria-hidden="true">← </span>Back to deck
    </button>
  </main>;
}
