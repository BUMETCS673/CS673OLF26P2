import React, { useEffect, useState } from 'react';
import CardForm from '../components/CardForm';
import CardRow from '../components/CardRow';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useDecksApi } from '../api/useDecksApi';

export default function DeckDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  return <div className="ws4"><RoutedDeckDetail key={id} id={id} location={location} navigate={navigate} /></div>;
}

function RoutedDeckDetail({ id, location, navigate }) {
  const decksApi = useDecksApi();
  // Consume the setup flag once. Back/Forward must not replay first-card setup.
  const [startAdding] = useState(Boolean(location.state?.startAdding));
  useEffect(() => {
    if (location.state?.startAdding) {
      const state = { ...location.state, startAdding: false };
      navigate(`${location.pathname}${location.search}${location.hash}`, { replace: true, state });
    }
  }, [location, navigate]);
  return <DeckDetailView api={decksApi} deckId={id} startAdding={startAdding}
    onBack={() => navigate('/decks')} />;
}

export function DeckDetailView({ api, deckId, onBack, startAdding = false }) {
  const [revision, setRevision] = useState(0);
  // Deck, cards and the load error in one state tagged with the request that produced
  // them, so `loading` is derived rather than switched on at the top of the effect --
  // see the same comment in DeckListPage. The page is mounted with key={id}, so a
  // different deck remounts this component rather than re-running the effect.
  const [result, setResult] = useState({ key: null, deck: null, cards: [], error: '' });
  const requestKey = `${deckId}#${revision}`;
  const loading = result.key !== requestKey;
  const { deck, cards, error } = result;
  const [adding, setAdding] = useState(startAdding);
  const [notice, setNotice] = useState('');

  function setCards(update) {
    setResult((current) => ({
      ...current,
      cards: typeof update === 'function' ? update(current.cards) : update,
    }));
  }

  useEffect(() => {
    let active = true;
    Promise.all([api.getDeck(deckId), api.listCards(deckId)])
      .then(([nextDeck, nextCards]) => { if (active) setResult({ key: requestKey, deck: nextDeck, cards: nextCards, error: '' }); })
      .catch((err) => { if (active) setResult({ key: requestKey, deck: null, cards: [], error: err.code === 'not_found' ? 'This deck could not be found.' : err.message || 'Could not load this deck.' }); });
    return () => { active = false; };
  }, [api, deckId, requestKey]);

  return <main className="ws4-page">
    <button className="text-button back-link" onClick={onBack}>← All decks</button>
    <p className="sr-only" role="status">{notice}</p>
    {loading ? <div className="state-panel" role="status">Loading your cards…</div>
      : error ? <div className="state-panel"><h1>Unable to open deck</h1><p className="error-message" role="alert">{error}</p>
        <button className="button secondary" onClick={() => setRevision((n) => n + 1)}>Try again</button></div>
      : deck && <>
        <div className="page-heading"><div><p className="eyebrow">Your deck · {cards.length} {cards.length === 1 ? 'card' : 'cards'}</p>
          <h1>{deck.name}</h1>{deck.description && <p className="subtitle deck-detail-description">{deck.description}</p>}</div>
          {!adding && <button className="button primary" onClick={() => { setNotice(''); setAdding(true); }}>+ Add card</button>}</div>
        {adding && <section className="card-composer" aria-labelledby="add-card-heading">
          <div className="composer-heading"><div><p className="eyebrow">{cards.length === 0 ? 'Your first flashcard' : 'One more idea'}</p>
            <h2 id="add-card-heading">{cards.length === 0 ? 'What do you want to remember?' : 'Add to your collection'}</h2></div>
            <span className="composer-count">{cards.length} saved</span></div>
          <CardForm cancelLabel={startAdding ? 'Finish for now' : 'Cancel'}
            onCancel={startAdding ? onBack : () => setAdding(false)} onSave={async (body) => {
            const card = await api.createCard(deck.id, body);
            setCards((items) => [...items, card]);
            setNotice(startAdding ? 'Card saved. Add another or finish for now.' : 'Card saved. Add another or cancel to return to your cards.');
          }} />
          <p className="composer-note">{notice || 'Your deck is saved. Cards are optional—you can add them anytime.'}</p>
        </section>}
        {cards.length > 0 && <div className="section-heading"><h2>Cards <span className="count-badge">{cards.length}</span></h2><span className="muted">Make each idea memorable.</span></div>}
        {cards.length === 0 ? !adding && <section className="empty-state empty-deck">
          <h2>This deck is empty</h2><p>Use “+ Add card” above to add a question and answer whenever you’re ready.</p>
        </section> : <ul className="card-list">{cards.map((card, index) => <CardRow key={card.id} card={card} index={index}
          onSave={async (id, body) => {
            const updated = await api.updateCard(id, body);
            setCards((items) => items.map((item) => item.id === id ? updated : item)); setNotice('Card updated.');
          }} onDelete={async (id) => {
            await api.deleteCard(id); setCards((items) => items.filter((item) => item.id !== id)); setNotice('Card deleted.');
          }} />)}</ul>}
      </>}
  </main>;
}
