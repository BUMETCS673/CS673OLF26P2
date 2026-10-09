/*
 * Step 0b: the placeholder.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component scaffolding
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/**
 * The generate form: three ways to ask for cards, and how many (F1).
 *
 * Step 0b's placeholder. F1 builds the form inside it, keeping these props and every
 * "Tests can rely on" item in C7 (code/plans/ITERATION_3_PLAN.md).
 *
 * props:
 *   deck        a Deck, from GET /api/decks/:id
 *   cardCount   number: the deck's card_count. Suggest more content needs 10 or more
 *   busy        boolean: a generate request is running
 *   error       an ApiError from the last generate request, or null
 *   onGenerate  (body) => Promise: sends one request, with a body exactly as in C2
 */
export default function GenerateForm() {
  return <p className="page-status">The form arrives in F1</p>;
}
