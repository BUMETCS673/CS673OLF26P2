import React, { useState } from 'react';
import CardForm from './CardForm';

export default function CardRow({ card, index, onSave, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');

  async function remove() {
    setDeleting(true); setError('');
    try { await onDelete(card.id); }
    catch (err) { setError(err.message || 'Could not delete this card. Please try again.'); }
    finally { setDeleting(false); }
  }

  return <li className="card-row">
    <div className="card-row-heading"><span className="eyebrow">Card {String(index + 1).padStart(2, '0')}</span>
      {!editing && !confirming && <div className="row-actions">
        <button className="text-button" onClick={() => setEditing(true)} aria-label={`Edit card ${index + 1}`}>Edit</button>
        <button className="text-button danger" onClick={() => setConfirming(true)} aria-label={`Delete card ${index + 1}`}>Delete</button>
      </div>}
    </div>
    {editing ? <CardForm initialValue={card} onCancel={() => setEditing(false)} onSave={async (body) => {
      await onSave(card.id, body); setEditing(false);
    }} /> : <div className="card-content">
      <div><span className="field-caption">Front</span><p>{card.front}</p></div>
      <div><span className="field-caption">Back</span><p>{card.back}</p></div>
    </div>}
    {confirming && <div className="delete-confirmation" role="group" aria-label={`Confirm deleting card ${index + 1}`}>
      <p>Delete this card? This cannot be undone.</p>
      <div className="form-actions">
        <button className="button destructive" disabled={deleting} onClick={remove}>{deleting ? 'Deleting…' : 'Delete card'}</button>
        <button className="button secondary" disabled={deleting} onClick={() => { setConfirming(false); setError(''); }}>Keep card</button>
      </div>
    </div>}
    {error && <p role="alert" className="error-message">{error}</p>}
  </li>;
}
