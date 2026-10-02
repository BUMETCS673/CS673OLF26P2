import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useDecksApi } from '../api/useDecksApi';
import { useStudyApi } from '../api/useStudyApi';
import '../study.css';

/**
 * The study page at /decks/:id/study (Iteration 2).
 *
 * The wrapper reads the route and the hooks, and StudyView takes everything as props, so
 * a test can render it with a fake `api` and a fixed clock (rule 12 in
 * code/plans/FINALIZE_ITERATION_2_PLAN.md). This is Step 0b's placeholder: F1 replaces
 * StudyView with the real session and keeps its props.
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
 * props:
 *   api     { getDeck(deckId), getDueCards(deckId), reviewCard(cardId, rating) }
 *   deckId  string, from the route
 *   onExit  () => void, back to the deck page
 *   now     () => number, in milliseconds. Defaults to Date.now; tests pass a fixed clock.
 *           The placeholder doesn't read it; F1's session does.
 */
export function StudyView({ api, deckId, onExit }) {
  // The deck or the load error, whichever arrives. The view is mounted with key={id}, so
  // it only ever loads one deck, and it's loading until one of the two is set.
  const [result, setResult] = useState({ deck: null, error: '' });
  const { deck, error } = result;

  useEffect(() => {
    let active = true;
    api.getDeck(deckId)
      .then((nextDeck) => { if (active) setResult({ deck: nextDeck, error: '' }); })
      .catch((err) => {
        if (active) setResult({ deck: null, error: err.code === 'not_found' ? 'This deck could not be found.' : err.message || 'Could not load this deck.' });
      });
    return () => { active = false; };
  }, [api, deckId]);

  return <main className="page">
    {error ? <><h1>Unable to study this deck</h1><p className="error-message" role="alert">{error}</p></>
      : deck ? <><p className="eyebrow">Study</p><h1>{deck.name}</h1><p className="subtitle">Study mode is on its way.</p></>
      : <p className="page-status" role="status">Loading…</p>}
    <button type="button" className="button secondary" onClick={onExit}>← Back to deck</button>
  </main>;
}
