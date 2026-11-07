import React, { useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { createOAuthApi } from '../api/oauth.js';
import { useApi } from '../api/useApi.js';
import { useLoad } from '../hooks/useLoad.js';

// What the MCP server's tools can do which the user reads before allowing an app
const ALLOWED = [
  'See your decks and the cards due in them',
  'Search the study materials learners have shared',
  'Add cards to your decks and start AI generation, which waits for your review',
];

export default function ConsentPage() {
  const { requestId } = useParams();
  const api = useApi(createOAuthApi);
  return <div className="ws4"><ConsentView api={api} requestId={requestId}
    leave={(url) => window.location.assign(url)} /></div>;
}

export function ConsentView({ api, requestId, leave }) {
  const load = useCallback(() => api.getConsent(requestId), [api, requestId]);
  const { data: consent, error: loadError, loading } = useLoad(load);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function decide(approve) {
    setBusy(true); setError('');
    try {
      const { redirect_url: url } = await api.decide(requestId, approve);
      leave(url); // the app finishes signing in or hears that the user said no
    } catch (err) {
      setError(err.message || 'Could not send your answer. Please try again.');
      setBusy(false);
    }
  }

  return <main className="ws4-page">
    {loading ? <div className="state-panel" role="status">Loading…</div>
      : loadError ? <div className="state-panel"><p role="alert" className="error-message">{loadError.message || 'Could not load this request.'}</p></div>
      : <section className="form-panel" aria-labelledby="consent-heading">
        <p className="eyebrow">Connect an app</p>
        <h1 id="consent-heading">Allow {consent.client_name} to use your Cadence account?</h1>
        <p className="muted">You’ll go back to {consent.redirect_host} afterward. You can disconnect it at any time.</p>
        <p>It will be able to:</p>
        <ul>{ALLOWED.map((item) => <li key={item}>{item}</li>)}</ul>
        {error && <p className="error-message" role="alert">{error}</p>}
        <div className="form-actions">
          <button className="button primary" disabled={busy} onClick={() => decide(true)}>Allow</button>
          <button className="button secondary" disabled={busy} onClick={() => decide(false)}>Deny</button>
        </div>
      </section>}
  </main>;
}
