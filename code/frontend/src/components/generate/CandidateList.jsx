/*
 * Step 0b: the placeholder.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component scaffolding
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 *
 * F2: the review list.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 * Human role: plan review, code review, and CI verification by Duc Anh Nguyen.
 */

/**
 * The review list: every suggestion, to accept or reject (F2).
 *
 * Keeps C7's props and every "Tests can rely on" item (code/plans/ITERATION_3_PLAN.md).
 * Decisions are final, so a decided card shows its outcome instead of buttons.
 *
 * props:
 *   generation      a Generation (C3)
 *   busy            boolean: an accept or reject request is running
 *   error           an ApiError from the last accept or reject, or null
 *   onAccept        (indexes) => Promise
 *   onReject        (indexes) => Promise
 *   onGenerateMore  () => void: back to the form, for another batch
 *   onBackToDeck    () => void
 */
export default function CandidateList({
  generation, busy, error, onAccept, onReject, onGenerateMore, onBackToDeck,
}) {
  const { cards, requested_count: requested } = generation;
  const pending = cards.filter((card) => card.status === 'pending').map((card) => card.index);
  const added = cards.filter((card) => card.status === 'accepted').length;

  return <section className="candidate-review" aria-labelledby="candidate-heading">
    <h2 id="candidate-heading">{plural(cards.length, 'suggestion')}</h2>
    {cards.length === 0
      ? <p className="candidate-note">Gemini couldn't write cards from that. Try a different prompt or file.</p>
      : cards.length < requested
        && <p className="candidate-note">Gemini returned {cards.length} of the {requested} you asked for.</p>}
    {error && <p className="error-message" role="alert">{error.message}</p>}

    {cards.length > 0 && <ol className="candidate-list">
      {cards.map((card) => <Candidate key={card.index} card={card} busy={busy}
        onAccept={onAccept} onReject={onReject} />)}
    </ol>}

    {pending.length > 0
      ? <div className="form-actions">
        <button type="button" className="button primary" disabled={busy}
          onClick={() => onAccept(pending)}>Accept all</button>
        <button type="button" className="button secondary" disabled={busy}
          onClick={() => onReject(pending)}>Reject all</button>
      </div>
      : <div className="candidate-summary">
        {cards.length > 0 && <p>{added === 0 ? 'No cards added' : `${plural(added, 'card')} added`}</p>}
        <div className="form-actions">
          {cards.length > 0 && <button type="button" className="button primary" disabled={busy}
            onClick={onBackToDeck}>Back to deck</button>}
          <button type="button" className="button secondary" disabled={busy}
            onClick={onGenerateMore}>Generate more</button>
        </div>
      </div>}
  </section>;
}

function Candidate({ card, busy, onAccept, onReject }) {
  const n = card.index + 1;
  const decided = card.status !== 'pending';
  return <li className={`panel candidate${decided ? ` candidate-${card.status}` : ''}`}>
    <div className="candidate-text">
      <p className="candidate-front">{card.front}</p>
      <p className="candidate-back">{card.back}</p>
    </div>
    <div className="candidate-actions">
      {card.status === 'accepted' && <span className="badge badge-blue">Added to deck</span>}
      {card.status === 'rejected' && <span className="badge">Rejected</span>}
      {!decided && <>
        <button type="button" className="button primary" disabled={busy}
          aria-label={`Accept suggestion ${n}`} onClick={() => onAccept([card.index])}>Accept</button>
        <button type="button" className="button ghost" disabled={busy}
          aria-label={`Reject suggestion ${n}`} onClick={() => onReject([card.index])}>Reject</button>
      </>}
    </div>
  </li>;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}
