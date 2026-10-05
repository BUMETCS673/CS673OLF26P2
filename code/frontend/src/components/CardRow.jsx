/*
 * F4: the schedule badge and the `now` prop.
 * AI Utilization: ~100% of those changes
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   UI component development
 * Human role: requirements (F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Nurzat Mukhamedali.
 */

import React, { useState } from 'react';
import CardForm from './CardForm';
import { describeSchedule } from '../study/describeSchedule.js';

// `now` (milliseconds) is read once per load by DeckDetailView, so every row's badge agrees.
export default function CardRow({ card, index, onSave, onDelete, now }) {
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
    <div className="card-row-heading"><div className="card-row-meta"><span className="eyebrow">Card {String(index + 1).padStart(2, '0')}</span>
      <span className="badge badge-blue">{describeSchedule(card, now)}</span></div>
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
