/*
 * F4: Study now, the due-count badge (refreshed after a card is added or deleted), and one
 * `now` for every CardRow.
 * AI Utilization: ~100% of those changes
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   UI component development
 * Human role: requirements (F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Nurzat Mukhamedali.
 */

/*
 * F3 (Iteration 3): the Generate with AI button and onGenerate.
 * AI Utilization: 90%
 * AI Tools Used: Claude
 * AI-Assisted Activities:
 *   - UI component development
 * Human role: checked against F3 in code/plans/ITERATION_3_PLAN.md, ran the tests, and
 * opened the PR, by Osasenaga Von Okunbor.
 */

/*
 * Iteration 3 refactor: loading through useLoad(), useApi() and deckLoadMessage().
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import React, { useCallback, useEffect, useState } from 'react';
import CardForm from '../components/CardForm';
import CardRow from '../components/CardRow';
import { deckLoadMessage } from '../components/deckLoadMessage.js';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { createDecksApi } from '../api/decks.js';
import { useApi } from '../api/useApi.js';
import { useLoad } from '../hooks/useLoad.js';
import { describeDueCounts } from '../study/describeSchedule.js';

export default function DeckDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  return <div className="ws4"><RoutedDeckDetail key={id} id={id} location={location} navigate={navigate} /></div>;
}

function RoutedDeckDetail({ id, location, navigate }) {
  const decksApi = useApi(createDecksApi);
  // Consume the setup flag once. Back/Forward must not replay first-card setup.
  const [startAdding] = useState(Boolean(location.state?.startAdding));
  useEffect(() => {
    if (location.state?.startAdding) {
      const state = { ...location.state, startAdding: false };
      navigate(`${location.pathname}${location.search}${location.hash}`, { replace: true, state });
    }
  }, [location, navigate]);
  return <DeckDetailView api={decksApi} deckId={id} startAdding={startAdding}
    onBack={() => navigate('/decks')} onStudy={() => navigate(`/decks/${id}/study`)}
    onGenerate={() => navigate(`/decks/${id}/generate`)} />;
}

export function DeckDetailView({ api, deckId, onBack, onStudy, onGenerate, startAdding = false }) {
  // The page is mounted with key={id}, so a different deck remounts this component rather
  // than loading again in place. `now` is taken once per load, for every CardRow.
  const load = useCallback(
    () => Promise.all([api.getDeck(deckId), api.listCards(deckId)])
      .then(([deck, cards]) => ({ deck, cards, now: Date.now() })),
    [api, deckId],
  );
  const { data, error: loadError, loading, reload, setData } = useLoad(load);
  const { deck = null, cards = [], now = 0 } = data ?? {};
  const error = loadError ? deckLoadMessage(loadError) : '';
  const [adding, setAdding] = useState(startAdding);
  const [notice, setNotice] = useState('');

  function setCards(update) {
    setData((current) => ({
      ...current,
      cards: typeof update === 'function' ? update(current.cards) : update,
    }));
  }

  // due_counts depend on the cards, so refresh the deck after adding or deleting one.
  // If the request fails, the old counts stay.
  function refreshDeck() {
    api.getDeck(deckId)
      .then((nextDeck) => setData((current) => ({ ...current, deck: nextDeck })))
      .catch(() => {});
  }

  const dueSummary = deck && describeDueCounts(deck.due_counts);

  return <main className="ws4-page">
    <button className="text-button back-link" onClick={onBack}>← All decks</button>
    <p className="sr-only" role="status">{notice}</p>
    {loading ? <div className="state-panel" role="status">Loading your cards…</div>
      : error ? <div className="state-panel"><h1>Unable to open deck</h1><p className="error-message" role="alert">{error}</p>
        <button className="button secondary" onClick={reload}>Try again</button></div>
      : deck && <>
        <div className="page-heading"><div><p className="eyebrow">Your deck · {cards.length} {cards.length === 1 ? 'card' : 'cards'}</p>
          <h1>{deck.name}</h1>{dueSummary && <span className="badge badge-gold due-summary">{dueSummary}</span>}
          {deck.description && <p className="subtitle deck-detail-description">{deck.description}</p>}</div>
          <div className="page-actions">
            {!adding && <button className="button secondary" onClick={() => { setNotice(''); setAdding(true); }}>+ Add card</button>}
            <button className="button secondary" onClick={onGenerate}>Generate with AI</button>
            {cards.length > 0 && <button className="button primary" onClick={onStudy}>{studyLabel(deck.due_counts)}</button>}</div></div>
        {adding && <section className="card-composer" aria-labelledby="add-card-heading">
          <div className="composer-heading"><div><p className="eyebrow">{cards.length === 0 ? 'Your first flashcard' : 'One more idea'}</p>
            <h2 id="add-card-heading">{cards.length === 0 ? 'What do you want to remember?' : 'Add to your collection'}</h2></div>
            <span className="composer-count">{cards.length} saved</span></div>
          <CardForm cancelLabel={startAdding ? 'Finish for now' : 'Cancel'}
            onCancel={startAdding ? onBack : () => setAdding(false)} onSave={async (body) => {
            const card = await api.createCard(deck.id, body);
            setCards((items) => [...items, card]);
            refreshDeck();
            setNotice(startAdding ? 'Card saved. Add another or finish for now.' : 'Card saved. Add another or cancel to return to your cards.');
          }} />
          <p className="composer-note">{notice || 'Your deck is saved. Cards are optional—you can add them anytime.'}</p>
        </section>}
        {cards.length > 0 && <div className="section-heading"><h2>Cards <span className="count-badge">{cards.length}</span></h2><span className="muted">Make each idea memorable.</span></div>}
        {cards.length === 0 ? !adding && <section className="empty-state empty-deck">
          <h2>This deck is empty</h2><p>Use “+ Add card” above to add a question and answer whenever you’re ready.</p>
        </section> : <ul className="card-list">{cards.map((card, index) => <CardRow key={card.id} card={card} index={index} now={now}
          onSave={async (id, body) => {
            const updated = await api.updateCard(id, body);
            setCards((items) => items.map((item) => item.id === id ? updated : item)); setNotice('Card updated.');
          }} onDelete={async (id) => {
            await api.deleteCard(id); setCards((items) => items.filter((item) => item.id !== id)); refreshDeck();
            setNotice('Card deleted.');
          }} />)}</ul>}
      </>}
  </main>;
}

/** "Study now · 9", or just "Study now" until the deck carries `due_counts` (B2). */
function studyLabel(dueCounts) {
  if (!dueCounts) return 'Study now';
  return `Study now · ${dueCounts.learning + dueCounts.review + dueCounts.new}`;
}
