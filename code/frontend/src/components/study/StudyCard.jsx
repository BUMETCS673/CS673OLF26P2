/**
 * One card in a study session. Step 0b's stub; F2 builds the real one.
 *
 * props:
 *   card      a Card; uses front, back, and state
 *   revealed  boolean: whether the answer is showing
 *
 * Tests can rely on: the front is always visible, and the back isn't in the DOM at all
 * until `revealed` is true. F1's tests depend on that, so F2 keeps it. See "The study
 * components" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
 */
export default function StudyCard({ card, revealed }) {
  return <section className="study-card">
    <p className="study-card-front">{card.front}</p>
    {revealed && <p className="study-card-back">{card.back}</p>}
  </section>;
}
