import { RATINGS } from '../../study/constants.js';

/**
 * The end of a study session. Step 0b's stub; F3 builds the real one.
 *
 * props:
 *   counts           { again, hard, good, easy }: the answers given this session
 *   nextLearningDue  ISO string or null: when the next learning card is due, if any
 *   now              number, in milliseconds. F3 uses it for "More cards in 25m"
 *   onStudyMore      () => void: fetch again and start a new session
 *   onExit           () => void: back to the deck
 *
 * Tests can rely on: the heading "Session complete" when any count is above 0, otherwise
 * "Nothing to study right now"; a "Back to deck" button that calls onExit; and, when
 * nextLearningDue is set, a "Study more" button that calls onStudyMore. F1's tests depend
 * on that, so F3 keeps it. See "The study components" in
 * code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */
export default function SessionSummary({ counts, nextLearningDue, onStudyMore, onExit }) {
  const answered = RATINGS.reduce((total, rating) => total + counts[rating], 0);
  return <section className="session-summary">
    <h2>{answered > 0 ? 'Session complete' : 'Nothing to study right now'}</h2>
    {answered > 0 && <p>{RATINGS.map((rating) => `${rating} ${counts[rating]}`).join(' · ')}</p>}
    {nextLearningDue && <button type="button" onClick={onStudyMore}>Study more</button>}
    <button type="button" onClick={onExit}>Back to deck</button>
  </section>;
}
