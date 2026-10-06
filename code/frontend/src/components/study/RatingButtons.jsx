/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { RATINGS } from '../../study/constants.js';
import { formatInterval } from '../../study/formatInterval.js';

const label = (rating) => rating[0].toUpperCase() + rating.slice(1);

/**
 * The four rating buttons (F2). Each one shows when the card would come back if you chose
 * it, from the intervals the backend sends (B3); the frontend only formats them (rule 6
 * in code/plans/LAB_3_PLAN.md). Each button's key, 1 to 4, is shown as a hint; F1 handles
 * the keys themselves.
 *
 * props:
 *   intervals  { again, hard, good, easy } in seconds, or undefined until B3 merges.
 *              Without them, the buttons show no interval (rule 10).
 *   disabled   boolean: a review is in flight
 *   onRate     (rating) => void
 *
 * Tests can rely on: four <button>s in RATINGS order, each accessible name starting with
 * Again, Hard, Good, or Easy ("Good, 1mo" when there's an interval); a click calls onRate
 * once with the lowercase rating; and `disabled` disables all four. F1's tests depend on
 * that. See "The study components" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */
export default function RatingButtons({ intervals, disabled, onRate }) {
  return <div className="rating-buttons" role="group" aria-label="Rate this card">
    {RATINGS.map((rating, index) => {
      const interval = intervals?.[rating] == null ? null : formatInterval(intervals[rating]);
      const key = String(index + 1);
      return <button key={rating} type="button" disabled={disabled}
        className={`button secondary rating-button rating-${rating}`}
        aria-label={interval ? `${label(rating)}, ${interval}` : label(rating)}
        aria-keyshortcuts={key} onClick={() => onRate(rating)}>
        <span className="rating-label">{label(rating)}</span>
        {interval && <span className="rating-interval">{interval}</span>}
        <kbd className="rating-key" aria-hidden="true">{key}</kbd>
      </button>;
    })}
  </div>;
}
