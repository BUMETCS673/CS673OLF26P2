/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { deckLoadMessage } from './deckLoadMessage.js';

/**
 * The full-page panel for a deck that couldn't be loaded. Try again is left out for a
 * missing deck, since retrying can't bring it back.
 *
 * props:
 *   title    the heading, e.g. "Unable to study this deck"
 *   error    the ApiError from the load
 *   onRetry  () => void
 *   onExit   () => void, back to the deck page
 */
export default function DeckLoadError({ title, error, onRetry, onExit }) {
  const notFound = error.code === 'not_found';
  return <main className="page">
    <section className="state-panel">
      <h1>{title}</h1>
      <p className="error-message" role="alert">{deckLoadMessage(error)}</p>
      <div className="form-actions">
        {!notFound && <button type="button" className="button primary" onClick={onRetry}>Try again</button>}
        <button type="button" className="button secondary" onClick={onExit}>Back to deck</button>
      </div>
    </section>
  </main>;
}
