/*
 * Step 0b: the placeholder.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component scaffolding
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/**
 * The review list: every suggestion, to accept or reject (F2).
 *
 * Step 0b's placeholder. F2 builds the list inside it, keeping these props and every
 * "Tests can rely on" item in C7 (code/plans/ITERATION_3_PLAN.md).
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
export default function CandidateList() {
  return <p className="page-status">The review list arrives in F2</p>;
}
