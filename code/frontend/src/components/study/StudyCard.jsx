/**
 * One card in a study session (F2): the front in large type, and below a divider, the
 * back once it's revealed. A badge says where the card is in its cycle.
 *
 * props:
 *   card      a Card; uses front, back, and state
 *   revealed  boolean: whether the answer is showing
 *
 * Tests can rely on: the front is always visible, and the back isn't in the DOM at all
 * until `revealed` is true, so it can't be read early, by eye or by a screen reader. F1's
 * tests depend on that. See "The study components" in
 * code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */

const STATE_LABELS = { new: 'New', learning: 'Learning', relearning: 'Relearning', review: 'Review' };

export default function StudyCard({ card, revealed }) {
  return <section className="panel study-card" aria-label="Flashcard">
    <span className="badge badge-blue">{STATE_LABELS[card.state] ?? card.state}</span>
    <p className="study-card-front">{card.front}</p>
    {/* Polite: the back is announced when it appears, without interrupting. */}
    <div className="study-card-answer" aria-live="polite">
      {revealed && <>
        <hr className="study-card-divider" />
        <p className="study-card-back">{card.back}</p>
      </>}
    </div>
  </section>;
}
