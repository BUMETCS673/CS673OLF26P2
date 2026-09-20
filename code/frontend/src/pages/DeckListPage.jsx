import React, { useEffect, useState } from 'react';
import DeckForm from '../components/DeckForm';

export default function DeckListPage({ api, onOpenDeck, onDeckCreated = onOpenDeck }) {
  const [decks, setDecks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api.listDecks().then((result) => { if (active) setDecks(result); })
      .catch((err) => { if (active) setError(err.message || 'Could not load your decks.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, revision]);

  async function remove(deck) {
    setBusy(true); setDeleteError('');
    try {
      await api.deleteDeck(deck.id);
      setDecks((items) => items.filter((item) => item.id !== deck.id));
      setDeleting(null); setNotice(`“${deck.name}” deleted.`);
    } catch (err) { setDeleteError(err.message || 'Could not delete this deck. Please try again.'); }
    finally { setBusy(false); }
  }

  return <main className="ws4-page">
    <div className="page-heading">
      <div><p className="eyebrow">Your learning library</p><h1>My decks</h1>
        <p className="subtitle">A little practice starts with a good collection.</p></div>
      {!creating && !loading && !error && decks.length > 0 && <button className="button primary" onClick={() => { setCreating(true); setEditing(null); }}>+ New deck</button>}
    </div>
    <p className="sr-only" role="status">{notice}</p>
    {creating && <section className="form-panel deck-setup" aria-labelledby="new-deck-heading">
      <p className="eyebrow">Start a collection</p>
      <h2 id="new-deck-heading">Create a deck</h2>
      <p className="muted">Give it a name, then add your first cards. You can also leave it empty for now.</p>
      <DeckForm onCancel={() => setCreating(false)} onSave={async (body) => {
        const deck = await api.createDeck(body);
        setDecks((items) => [...items, deck]); setCreating(false); setNotice(`“${deck.name}” created.`);
        onDeckCreated(deck.id);
      }} />
    </section>}
    {loading ? <div className="state-panel" role="status">Loading your decks…</div>
      : error ? <div className="state-panel"><p role="alert" className="error-message">{error}</p>
        <button className="button secondary" onClick={() => setRevision((n) => n + 1)}>Try again</button></div>
      : decks.length === 0 ? !creating && <section className="empty-state"><div className="empty-icon" aria-hidden="true">▤</div>
        <h2>Your first deck starts here</h2><p>Give a topic a home, then add the things you want to remember.</p>
        {!creating && <button className="button primary" onClick={() => setCreating(true)}>Create your first deck</button>}
      </section> : <>
        <div className="section-heading"><h2>All decks <span className="count-badge">{decks.length}</span></h2>
          <span className="muted">{decks.reduce((total, deck) => total + deck.card_count, 0)} cards in your library</span></div>
        <ul className="deck-grid">{decks.map((deck) => <li className="deck-tile" key={deck.id}>
          {editing === deck.id ? <><h2>Edit deck</h2><DeckForm initialValue={deck} onCancel={() => setEditing(null)} onSave={async (body) => {
            const updated = await api.updateDeck(deck.id, body);
            setDecks((items) => items.map((item) => item.id === deck.id ? updated : item));
            setEditing(null); setNotice('Deck updated.');
          }} /></> : <>
            <div className="deck-tile-top"><span className="deck-icon" aria-hidden="true">▤</span>
              <span className="card-count">{deck.card_count} {deck.card_count === 1 ? 'card' : 'cards'}</span></div>
            <h2><button className="deck-title" onClick={() => onOpenDeck(deck.id)}>{deck.name}</button></h2>
            <p className="deck-description">{deck.description || 'A fresh space for something worth remembering.'}</p>
            <div className="deck-footer"><button className="text-button open-deck" onClick={() => onOpenDeck(deck.id)} aria-label={`Open ${deck.name}`}>Open deck <span aria-hidden="true">↗</span></button>
              <div className="row-actions"><button className="text-button" disabled={deleting === deck.id} onClick={() => { setEditing(deck.id); setCreating(false); }} aria-label={`Edit ${deck.name}`}>Edit</button>
                <button className="text-button danger" disabled={busy} onClick={() => { setDeleting(deck.id); setDeleteError(''); }} aria-label={`Delete ${deck.name}`}>Delete</button></div></div>
            {deleting === deck.id && <div className="delete-confirmation" role="group" aria-label={`Confirm deleting ${deck.name}`}>
              <p>Delete “{deck.name}” and all {deck.card_count} {deck.card_count === 1 ? 'card' : 'cards'}? This cannot be undone.</p>
              <div className="form-actions"><button className="button destructive" disabled={busy} onClick={() => remove(deck)}>{busy ? 'Deleting…' : 'Delete deck'}</button>
                <button className="button secondary" disabled={busy} onClick={() => { setDeleting(null); setDeleteError(''); }}>Keep deck</button></div>
              {deleteError && <p role="alert" className="error-message">{deleteError}</p>}
            </div>}
          </>}
        </li>)}</ul>
      </>}
  </main>;
}
