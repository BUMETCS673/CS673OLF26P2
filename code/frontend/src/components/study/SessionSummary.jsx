/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: requirements (F3 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Duc Anh Nguyen.
 */

import { RATINGS } from '../../study/constants.js';
import { formatInterval } from '../../study/formatInterval.js';

const label = (rating) => rating[0].toUpperCase() + rating.slice(1);

/**
 * The end of a study session (F3): how many cards were answered and how, and when the next
 * learning card comes back. With nothing answered, it's the empty state instead.
 *
 * props:
 *   counts           { again, hard, good, easy }: the answers given this session
 *   nextLearningDue  ISO string or null: when the next learning card is due, if any
 *   now              number, in milliseconds, for "More cards in 25m"
 *   onStudyMore      () => void: fetch again and start a new session
 *   onExit           () => void: back to the deck
 *
 * Tests can rely on: the heading "Session complete" when any count is above 0, otherwise
 * "Nothing to study right now"; a "Back to deck" button that calls onExit; and, when
 * nextLearningDue is set, a "Study more" button that calls onStudyMore. F1's tests depend
 * on that. See "The study components" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */
export default function SessionSummary({ counts, nextLearningDue, now, onStudyMore, onExit }) {
  const answered = RATINGS.reduce((total, rating) => total + counts[rating], 0);
  // The backend sends due times; the frontend only formats the wait (rule 6, Lab 3 plan).
  const waitSeconds = nextLearningDue ? Math.max(0, (Date.parse(nextLearningDue) - now) / 1000) : null;

  return <section className="panel session-summary">
    {answered > 0 ? <>
      <h2>Session complete</h2>
      <p className="summary-total">{answered} {answered === 1 ? 'card' : 'cards'}</p>
      <ul className="summary-counts" aria-label="Answers by rating">
        {RATINGS.map((rating) => <li key={rating} className={`summary-count rating-${rating}`}>
          <span className="summary-count-label">{label(rating)}</span>
          <span className="summary-count-value">{counts[rating]}</span>
        </li>)}
      </ul>
    </> : <>
      <h2>Nothing to study right now</h2>
      <p className="subtitle">No cards in this deck are due yet.</p>
    </>}

    {waitSeconds !== null && <p className="summary-next">More cards in {formatInterval(waitSeconds)}</p>}

    <div className="summary-actions">
      {nextLearningDue && <button type="button" className="button primary" onClick={onStudyMore}>
        Study more
      </button>}
      <button type="button" className={`button ${nextLearningDue ? 'secondary' : 'primary'}`} onClick={onExit}>
        Back to deck
      </button>
    </div>
  </section>;
}
