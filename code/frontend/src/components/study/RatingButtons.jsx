import { RATINGS } from '../../study/constants.js';

const label = (rating) => rating[0].toUpperCase() + rating.slice(1);

/**
 * The four rating buttons. Step 0b's stub; F2 builds the real ones.
 *
 * props:
 *   intervals  { again, hard, good, easy } in seconds, from B3, or undefined until it
 *              merges. F2 shows formatInterval() of each one under its button.
 *   disabled   boolean: a review is in flight
 *   onRate     (rating) => void
 *
 * Tests can rely on: four <button>s in RATINGS order, each accessible name starting with
 * Again, Hard, Good, or Easy; a click calls onRate once with the lowercase rating; and
 * `disabled` disables all four. F1's tests depend on that, so F2 keeps it. See "The study
 * components" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */
export default function RatingButtons({ disabled, onRate }) {
  return <div className="rating-buttons" role="group" aria-label="Rate this card">
    {RATINGS.map((rating) => <button key={rating} type="button" disabled={disabled}
      onClick={() => onRate(rating)}>{label(rating)}</button>)}
  </div>;
}
