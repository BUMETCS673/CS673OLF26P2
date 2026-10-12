/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   UI component development
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/**
 * The label on a card the AI wrote (C7). F3 places it in the deck's card list and on the
 * study card, wherever `card.origin === 'ai'`. Quiet on purpose: it informs without
 * competing with the state badge beside it.
 */
export default function AiBadge() {
  return <span className="badge badge-ai" title="Written by AI (Google Gemini) and accepted by you">AI-generated</span>;
}
