/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI page development
 *   Documentation
 * Human role: requirements (F1 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Duc Anh Nguyen.
 *
 * Iteration 3, F6: typed mode.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   UI page development
 * Human role: requirements (F6 in code/plans/ITERATION_3_PLAN.md), direction, and review by
 * Nurzat Mukhamedali.
 *
 * Iteration 3 refactor: loading through useLoad(), useApi() and DeckLoadError.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { createDecksApi } from '../api/decks.js';
import { createStudyApi } from '../api/study.js';
import { useApi } from '../api/useApi.js';
import DeckLoadError from '../components/DeckLoadError.jsx';
import { useLoad } from '../hooks/useLoad.js';
import RatingButtons from '../components/study/RatingButtons.jsx';
import SessionSummary from '../components/study/SessionSummary.jsx';
import StudyCard from '../components/study/StudyCard.jsx';
import StudyModeToggle from '../components/study/StudyModeToggle.jsx';
import TypedAnswer from '../components/study/TypedAnswer.jsx';
import { RATINGS } from '../study/constants.js';
import { initSession, sessionReducer } from '../study/session.js';
import { checkTypedAnswer } from '../study/typedAnswer.js';
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
  const decksApi = useApi(createDecksApi);
  const studyApi = useApi(createStudyApi);
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
  // Try again and Study more both reload. The session is keyed on the revision, so Study
  // more mounts a new session with a fresh reducer instead of needing a "restart" action.
  const load = useCallback(
    () => Promise.all([api.getDeck(deckId), api.getDueCards(deckId)]),
    [api, deckId],
  );
  const { data, error, loading, revision, reload } = useLoad(load);
  // 'flashcard' or 'typed'. It lives here, above the keyed session, so Study more keeps it;
  // a new page load starts in flashcard mode (decision A13).
  const [mode, setMode] = useState('flashcard');

  if (loading) {
    return <main className="page">
      <p className="page-status" role="status">Loading…</p>
    </main>;
  }

  if (error) {
    return <DeckLoadError title="Unable to study this deck" error={error} onRetry={reload} onExit={onExit} />;
  }

  const [deck, due] = data;
  return <StudySession key={revision} api={api} deck={deck} due={due} now={now}
    mode={mode} onModeChange={setMode} onExit={onExit} onStudyMore={reload} />;
}

/**
 * The ignored targets for the keyboard shortcuts: anywhere the learner is typing. Radios and
 * checkboxes aren't typing, so the shortcuts still work right after the mode toggle is clicked.
 */
const isTyping = (target) => {
  if (target?.tagName === 'INPUT') return !['radio', 'checkbox'].includes(target.type);
  return ['TEXTAREA', 'SELECT'].includes(target?.tagName) || Boolean(target?.isContentEditable);
};

/** One session over `due`, from the first card to the summary. */
function StudySession({ api, deck, due, now, mode, onModeChange, onExit, onStudyMore }) {
  const [state, dispatch] = useReducer(sessionReducer, { due, now: now() }, initSession);
  // Rule 11: one review request per card shown. The ref holds the session state the request
  // was sent from, so a second click or key press made from that same state does nothing.
  // A flag isn't enough: it would clear before React re-renders and re-attaches the
  // keydown listener, and the stale listener would rate the answered card again.
  const sentFrom = useRef(null);
  const [saving, setSaving] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const { current, revealed, answer } = state;

  const reveal = useCallback(() => dispatch({ type: 'reveal' }), []);
  const check = useCallback((typed) => dispatch({
    type: 'reveal',
    answer: { typed, ...checkTypedAnswer(current.back, typed) },
  }), [current]);

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

  // Space reveals (in flashcard mode only), and 1-4 rate once the answer is showing
  // (decision P10). In typed mode, Enter checks, and then Enter on the focused suggested
  // button accepts it; the browser does both.
  useEffect(() => {
    if (state.finished) return undefined;
    function onKeyDown(event) {
      if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTyping(event.target)) return;
      if (event.key === ' ') {
        // A focused button handles Space itself; doing it here as well would act twice.
        if (event.target?.tagName === 'BUTTON' || revealed || mode === 'typed') return;
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
  }, [state.finished, revealed, mode, reveal, rate]);

  if (state.finished) {
    return <main className="page study-session">
      <p className="eyebrow">{deck.name}</p>
      <SessionSummary counts={state.counts} nextLearningDue={state.nextLearningDue} now={now()}
        onStudyMore={onStudyMore} onExit={onExit} />
    </main>;
  }

  const left = state.main.length + state.learning.length + (current ? 1 : 0);
  // Switching modes redraws a card that isn't revealed yet. Once it is, the answer (and any
  // suggestion) stays, and the new mode starts with the next card.
  const typing = !revealed && mode === 'typed';
  let hint = 'Press Space to show the answer';
  if (answer) hint = 'Press Enter to accept the suggestion, or 1–4 to choose';
  else if (revealed) hint = 'Press 1–4 to rate';
  else if (typing) hint = 'Press Enter to check';
  return <main className="page study-session">
    <div className="study-heading">
      <div>
        <p className="eyebrow">Study</p>
        <h1>{deck.name}</h1>
      </div>
      <div className="study-heading-side">
        <StudyModeToggle mode={mode} onChange={onModeChange} />
        <p className="study-left">{left} {left === 1 ? 'card' : 'cards'} left</p>
      </div>
    </div>

    <StudyCard card={current} revealed={revealed} />

    <div className="study-actions">
      {(typing || answer) && <TypedAnswer key={current.id} answer={answer} disabled={saving}
        onSubmit={check} />}
      {revealed && <RatingButtons intervals={current.intervals} disabled={saving} onRate={rate}
        suggested={answer?.suggestedRating} />}
      {!revealed && !typing
        && <button type="button" className="button primary study-reveal" onClick={reveal}>Show answer</button>}
      {reviewError && <p className="error-message" role="alert">{reviewError}</p>}
      <p className="study-hint">{hint}</p>
    </div>

    <button type="button" className="text-button study-exit" onClick={onExit}>
      <span aria-hidden="true">← </span>Back to deck
    </button>
  </main>;
}
