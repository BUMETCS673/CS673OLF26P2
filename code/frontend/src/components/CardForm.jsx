import React, { useId, useState } from 'react';

export default function CardForm({ initialValue, onSave, onCancel, cancelLabel = 'Cancel' }) {
  const id = useId();
  const [front, setFront] = useState(initialValue?.front ?? '');
  const [back, setBack] = useState(initialValue?.back ?? '');
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    const next = {};
    for (const [field, value] of Object.entries({ front, back })) {
      if (!value.trim()) next[field] = `The ${field} of your card cannot be blank.`;
      else if (value.length > 2000) next[field] = 'Use 2,000 characters or fewer.';
    }
    setErrors(next);
    setError('');
    if (Object.keys(next).length) return;
    setSaving(true);
    try {
      await onSave({ front: front.trim(), back: back.trim() });
      if (!initialValue) { setFront(''); setBack(''); }
    } catch (err) {
      setError(err.message || 'Could not save this card. Please try again.');
    } finally { setSaving(false); }
  }

  return <form className="ws4-form flashcard-form" onSubmit={submit} noValidate>
    <fieldset disabled={saving}>
      <div className="card-fields">
        {[['front', front, setFront, 'Question or prompt'], ['back', back, setBack, 'Answer or explanation']].map(([field, value, setter, placeholder]) =>
          <div key={field}>
            <label htmlFor={`${id}-${field}`}>{field === 'front' ? 'Front' : 'Back'}</label>
            <textarea id={`${id}-${field}`} rows={3} value={value} required maxLength={2000}
              autoFocus={field === 'front'} onChange={(e) => setter(e.target.value)} placeholder={placeholder}
              aria-invalid={!!errors[field]} aria-describedby={`${id}-${field}-hint`} />
            <p id={`${id}-${field}-hint`} className={errors[field] ? 'field-error' : 'field-hint'}
              role={errors[field] ? 'alert' : undefined}>{errors[field] || `${value.length.toLocaleString()} / 2,000 characters`}</p>
          </div>)}
      </div>
      {error && <p className="error-message" role="alert">{error}</p>}
      <div className="form-actions">
        <button className="button primary" type="submit">{saving ? 'Saving…' : initialValue ? 'Save changes' : 'Save card'}</button>
        <button className="button secondary" type="button" onClick={onCancel}>{cancelLabel}</button>
      </div>
    </fieldset>
  </form>;
}
