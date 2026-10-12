/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

/** What to tell the learner when a deck couldn't be loaded. */
export function deckLoadMessage(error) {
  return error.code === 'not_found'
    ? 'This deck could not be found.'
    : error.message || 'Could not load this deck.';
}
