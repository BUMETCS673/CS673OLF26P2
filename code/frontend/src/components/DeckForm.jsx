import React, { useId, useState } from 'react';

export default function DeckForm({ initialValue, onSave, onCancel }) {
  const id = useId();
  const [name, setName] = useState(initialValue?.name ?? '');
  const [description, setDescription] = useState(initialValue?.description ?? '');
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    const next = {};
    if (!name.trim()) next.name = 'Give your deck a name.';
    else if (name.trim().length > 120) next.name = 'Use 120 characters or fewer.';
    if (description.length > 1000) next.description = 'Use 1,000 characters or fewer.';
    setErrors(next);
    setError('');
    if (Object.keys(next).length) return;
    setSaving(true);
    try {
      await onSave({ name: name.trim(), description: description.trim() });
    } catch (err) {
      setError(err.message || 'Could not save this deck. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return <form className="ws4-form" onSubmit={submit} noValidate>
    <fieldset disabled={saving}>
      <label htmlFor={`${id}-name`}>Deck name</label>
      <input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)}
        autoFocus required maxLength={120} placeholder="e.g. Spanish vocabulary"
        aria-invalid={!!errors.name} aria-describedby={errors.name ? `${id}-name-error` : undefined} />
      {errors.name && <p className="field-error" id={`${id}-name-error`} role="alert">{errors.name}</p>}
      <label htmlFor={`${id}-description`}>Description <span className="optional">optional</span></label>
      <textarea id={`${id}-description`} rows={3} value={description} maxLength={1000}
        onChange={(e) => setDescription(e.target.value)} placeholder="What will you learn?"
        aria-invalid={!!errors.description} aria-describedby={errors.description ? `${id}-description-error` : undefined} />
      {errors.description && <p className="field-error" id={`${id}-description-error`} role="alert">{errors.description}</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      <div className="form-actions">
        <button className="button primary" type="submit">{saving ? 'Saving…' : initialValue ? 'Save changes' : 'Create deck'}</button>
        <button className="button secondary" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </fieldset>
  </form>;
}
