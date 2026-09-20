import React, { useEffect, useState } from 'react';
import CardForm from '../components/CardForm';
import CardRow from '../components/CardRow';

export default function DeckDetailPage({ api, deckId, onBack, startAdding = false }) {
  const [deck, setDeck] = useState(null);
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [adding, setAdding] = useState(startAdding);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setAdding(startAdding); setDeck(null); setCards([]);
    Promise.all([api.getDeck(deckId), api.listCards(deckId)])
      .then(([nextDeck, nextCards]) => { if (active) { setDeck(nextDeck); setCards(nextCards); } })
      .catch((err) => { if (active) setError(err.code === 'not_found' ? 'This deck could not be found.' : err.message || 'Could not load this deck.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, deckId, revision, startAdding]);

  return <main className="ws4-page">
    <button className="text-button back-link" onClick={onBack}>← All decks</button>
    <p className="sr-only" role="status">{notice}</p>
    {loading ? <div className="state-panel" role="status">Loading your cards…</div>
      : error ? <div className="state-panel"><h1>Unable to open deck</h1><p className="error-message" role="alert">{error}</p>
        <button className="button secondary" onClick={() => setRevision((n) => n + 1)}>Try again</button></div>
      : deck && <>
        <div className="page-heading"><div><p className="eyebrow">Your deck · {cards.length} {cards.length === 1 ? 'card' : 'cards'}</p>
          <h1>{deck.name}</h1>{deck.description && <p className="subtitle deck-detail-description">{deck.description}</p>}</div>
          {!adding && <button className="button primary" onClick={() => setAdding(true)}>+ Add card</button>}</div>
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
          <p className="composer-note" role="status">{notice || 'Your deck is saved. Cards are optional—you can add them anytime.'}</p>
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
