import React, { useCallback, useId, useState } from 'react';
import { createTokensApi } from '../api/tokens.js';
import { useApi } from '../api/useApi.js';
import { useLoad } from '../hooks/useLoad.js';
import '../tokens.css';

const NAME_MAX = 120;
// the expiry choices with Never sent to the API as null
const EXPIRY_OPTIONS = [['30', '30 days'], ['90', '90 days'], ['365', '1 year'], ['never', 'Never']];

// The JSON that Claude Code (a project's .mcp.json), Cursor and VS Code read for a remote server.
export function mcpConfig(url, token) {
  const server = { type: 'http', url, headers: { Authorization: `Bearer ${token}` } };
  return JSON.stringify({ mcpServers: { cadence: server } }, null, 2);
}

export function claudeCodeCommand(url, token) {
  return `claude mcp add --transport http cadence ${url} --header "Authorization: Bearer ${token}"`;
}

const formatDate = (value) => new Date(value).toLocaleDateString();

export default function TokensPage() {
  const api = useApi(createTokensApi);
  // the frontend proxies /api and the MCP server is on this same origin
  return <div className="ws4"><TokensView api={api} serverUrl={`${window.location.origin}/api/mcp`} /></div>;
}

function CopyBlock({ label, text }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false); // a blocked clipboard leaves the text there to select by hand
    }
  }
  return <div className="copy-block">
    <div className="copy-block-top"><span className="muted">{label}</span>
      <button type="button" className="text-button" onClick={copy} aria-label={`Copy ${label}`}>{copied ? 'Copied' : 'Copy'}</button></div>
    <pre><code>{text}</code></pre>
  </div>;
}

export function TokensView({ api, serverUrl }) {
  const id = useId();
  const load = useCallback(() => api.listTokens(), [api]);
  const { data, error: loadError, loading, reload, setData: setTokens } = useLoad(load);
  const tokens = data ?? [];
  const [name, setName] = useState('');
  const [expiry, setExpiry] = useState('90');
  const [created, setCreated] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function create(event) {
    event.preventDefault();
    if (!name.trim()) { setError('Give the token a name.'); return; }
    setBusy(true); setError('');
    try {
      const token = await api.createToken(name.trim(), expiry === 'never' ? null : Number(expiry));
      setTokens((items) => [...items, token]);
      setCreated(token); setName('');
    } catch (err) { setError(err.message || 'Could not create a token. Please try again.'); }
    finally { setBusy(false); }
  }

  async function revoke(token) {
    setBusy(true); setError('');
    try {
      await api.revokeToken(token.id);
      setTokens((items) => items.filter((item) => item.id !== token.id));
      setConfirming(null);
      if (created?.id === token.id) setCreated(null);
    } catch (err) { setError(err.message || 'Could not revoke this token. Please try again.'); }
    finally { setBusy(false); }
  }

  return <main className="ws4-page">
    <div className="page-heading"><div><p className="eyebrow">Connect an AI assistant</p><h1>Access tokens</h1>
      <p className="subtitle">A token lets an MCP client like Claude search your materials and work with your decks.</p></div></div>

    <section className="form-panel" aria-labelledby={`${id}-new`}>
      <h2 id={`${id}-new`}>New token</h2>
      <form className="ws4-form" onSubmit={create} noValidate>
        <fieldset disabled={busy}>
          <label htmlFor={`${id}-name`}>Name</label>
          <input id={`${id}-name`} value={name} maxLength={NAME_MAX} placeholder="e.g. Claude Code"
            onChange={(e) => setName(e.target.value)} />
          <label htmlFor={`${id}-expiry`}>Expires after</label>
          <select id={`${id}-expiry`} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
            {EXPIRY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {error && <p className="error-message" role="alert">{error}</p>}
          <div className="form-actions"><button className="button primary" type="submit">{busy ? 'Working…' : 'Create token'}</button></div>
        </fieldset>
      </form>
      {created && <div className="token-reveal">
        <p role="status"><strong>Copy “{created.name}” now.</strong> Only a hash is kept, so it can’t be shown again.</p>
        <CopyBlock label="token" text={created.token} />
        <CopyBlock label="MCP client config" text={mcpConfig(serverUrl, created.token)} />
        <CopyBlock label="Claude Code command" text={claudeCodeCommand(serverUrl, created.token)} />
      </div>}
    </section>

    {loading ? <div className="state-panel" role="status">Loading your tokens…</div>
      : loadError ? <div className="state-panel"><p role="alert" className="error-message">{loadError.message || 'Could not load your tokens.'}</p>
        <button className="button secondary" onClick={reload}>Try again</button></div>
      : tokens.length === 0 ? <p className="muted">No tokens yet.</p>
      : <ul className="token-list">{tokens.map((token) => <li key={token.id}>
        <div><strong>{token.name}</strong>
          <p className="muted">Created {formatDate(token.created_at)} · {token.last_used_at ? `Last used ${formatDate(token.last_used_at)}` : 'Never used'} · {token.expires_at ? `Expires ${formatDate(token.expires_at)}` : 'Never expires'}</p>
          {confirming === token.id && <div className="delete-confirmation" role="group" aria-label={`Confirm revoking ${token.name}`}>
            <p>Revoke “{token.name}”? Any app using it will stop working.</p>
            <div className="form-actions"><button className="button destructive" disabled={busy} onClick={() => revoke(token)}>{busy ? 'Revoking…' : 'Revoke token'}</button>
              <button className="button secondary" disabled={busy} onClick={() => setConfirming(null)}>Keep token</button></div>
          </div>}</div>
        {confirming !== token.id && <button className="text-button danger" disabled={busy} onClick={() => setConfirming(token.id)} aria-label={`Revoke ${token.name}`}>Revoke</button>}
      </li>)}</ul>}

    <ConnectedApps api={api} />
  </main>;
}

// Apps that connected over OAuth after the user approved them on the consent page.
function ConnectedApps({ api }) {
  const load = useCallback(() => api.listApps(), [api]);
  const { data, error: loadError, loading, setData: setApps } = useLoad(load);
  const apps = data ?? [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function disconnect(app) {
    setBusy(true); setError('');
    try {
      await api.disconnectApp(app.client_id);
      setApps((items) => items.filter((item) => item.client_id !== app.client_id));
    } catch (err) { setError(err.message || 'Could not disconnect this app. Please try again.'); }
    finally { setBusy(false); }
  }

  return <section className="connected-apps" aria-labelledby="connected-apps-heading">
    <h2 id="connected-apps-heading">Connected apps</h2>
    {error && <p className="error-message" role="alert">{error}</p>}
    {loading ? <p className="muted" role="status">Loading connected apps…</p>
      : loadError ? <p className="error-message" role="alert">{loadError.message || 'Could not load connected apps.'}</p>
      : apps.length === 0 ? <p className="muted">No apps connected. Claude or ChatGPT will ask you to approve them here.</p>
      : <ul className="token-list">{apps.map((app) => <li key={app.client_id}>
        <div><strong>{app.name || 'Unnamed app'}</strong>
          <p className="muted">Connected {formatDate(app.connected_at)} · {app.last_used_at ? `Last used ${formatDate(app.last_used_at)}` : 'Never used'}</p></div>
        <button className="text-button danger" disabled={busy} onClick={() => disconnect(app)} aria-label={`Disconnect ${app.name || 'Unnamed app'}`}>Disconnect</button>
      </li>)}</ul>}
  </section>;
}
