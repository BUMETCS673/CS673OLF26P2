/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI page development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 *
 * Iteration 3 refactor: loading through useLoad(), useApi() and DeckLoadError.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { createDecksApi } from '../api/decks.js';
import { createGenerateApi } from '../api/generate.js';
import { useApi } from '../api/useApi.js';
import DeckLoadError from '../components/DeckLoadError.jsx';
import { useLoad } from '../hooks/useLoad.js';
import CandidateList from '../components/generate/CandidateList.jsx';
import GenerateForm from '../components/generate/GenerateForm.jsx';
import '../generate.css';

/**
 * The generate page at /decks/:id/generate (Iteration 3, Step 0b).
 *
 * The wrapper reads the route and the hooks, and GenerateView takes everything as props,
 * so a test can render it with a fake `api` (rule 12). See C7 in
 * code/plans/ITERATION_3_PLAN.md.
 */
export default function GeneratePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const decksApi = useApi(createDecksApi);
  const generateApi = useApi(createGenerateApi);
  // Both hooks memoize on the session, so this only changes when the session does.
  const api = useMemo(() => ({ getDeck: decksApi.getDeck, ...generateApi }), [decksApi, generateApi]);
  // key={id}: a different deck mounts a fresh view, as on the study page.
  return <div className="generate">
    <GenerateView key={id} api={api} deckId={id} onExit={() => navigate(`/decks/${id}`)} />
  </div>;
}

/**
 * Loads the deck, then shows the form (F1) until a batch arrives, and the review list (F2)
 * after. Never both.
 *
 * props:
 *   api     { getDeck(deckId), generate(deckId, body), acceptCards(id, indexes), rejectCards(id, indexes) }
 *   deckId  string, from the route
 *   onExit  () => void, back to the deck page
 */
export function GenerateView({ api, deckId, onExit }) {
  // Try again and Generate more both reload the deck.
  const load = useCallback(() => api.getDeck(deckId), [api, deckId]);
  const { data: deck, error, loading, reload } = useLoad(load);

  const [generation, setGeneration] = useState(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);
  const [listError, setListError] = useState(null);
  // Rule 21: one generate request at a time, because every one spends real quota. `busy`
  // disables the button, but a second click can land before React re-renders.
  const generating = useRef(false);

  const generate = useCallback(async (body) => {
    if (generating.current) return;
    generating.current = true;
    setBusy(true);
    setFormError(null);
    try {
      setGeneration(await api.generate(deckId, body));
    } catch (err) {
      // A 401 is the adapter's job: it signs out, and ProtectedRoute redirects.
      if (err.code !== 'unauthorized') setFormError(err);
    } finally {
      generating.current = false;
      setBusy(false);
    }
  }, [api, deckId]);

  // Accept and reject are safe to repeat, since the server skips decided cards, so
  // `busy` is enough here (rule 21).
  const decide = useCallback(async (send) => {
    setBusy(true);
    setListError(null);
    try {
      setGeneration(await send());
    } catch (err) {
      if (err.code !== 'unauthorized') setListError(err);
    } finally {
      setBusy(false);
    }
  }, []);

  const generationId = generation?.id;
  const accept = useCallback(
    (indexes) => decide(async () => (await api.acceptCards(generationId, indexes)).generation),
    [api, decide, generationId],
  );
  const reject = useCallback(
    (indexes) => decide(() => api.rejectCards(generationId, indexes)),
    [api, decide, generationId],
  );

  // Back to the form, with the deck loaded again so cardCount includes what was accepted.
  const generateMore = useCallback(() => {
    setGeneration(null);
    setFormError(null);
    setListError(null);
    reload();
  }, [reload]);

  if (loading) {
    return <main className="page">
      <p className="page-status" role="status">Loading…</p>
    </main>;
  }

  if (error) {
    return <DeckLoadError title="Unable to generate cards" error={error} onRetry={reload} onExit={onExit} />;
  }

  return <main className="page generate-page">
    <button type="button" className="text-button generate-back" onClick={onExit}>
      <span aria-hidden="true">← </span>Back to deck
    </button>
    <div className="page-heading">
      <div>
        <p className="eyebrow">Generate with AI</p>
        <h1>{deck.name}</h1>
      </div>
    </div>

    {generation
      ? <CandidateList generation={generation} busy={busy} error={listError}
        onAccept={accept} onReject={reject} onGenerateMore={generateMore} onBackToDeck={onExit} />
      : <section className="form-panel generate-form-panel">
        <GenerateForm deck={deck} cardCount={deck.card_count} busy={busy} error={formError}
          onGenerate={generate} />
      </section>}
  </main>;
}
