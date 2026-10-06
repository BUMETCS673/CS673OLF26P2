/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   Utility function development
 *   Documentation
 * Human role: requirements (F4 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
 * and review by Nurzat Mukhamedali.
 */

import { formatInterval } from './formatInterval.js';

/**
 * Short labels for the deck pages (Iteration 2, F4), built on formatInterval(). Pure: the
 * caller passes `now` in milliseconds, so every row on a page agrees.
 */

const STATE_LABELS = {
  new: 'New',
  learning: 'Learning',
  review: 'Review',
  relearning: 'Relearning',
};

/** Where a card stands: "New", "Learning · in 6m", "Review · due now". */
export function describeSchedule(card, now) {
  const label = STATE_LABELS[card.state] ?? STATE_LABELS.new;
  if (card.state === 'new' || !card.due_at) return label;

  const seconds = (Date.parse(card.due_at) - now) / 1000;
  return seconds <= 0 ? `${label} · due now` : `${label} · in ${formatInterval(seconds)}`;
}

/**
 * A deck's waiting cards: "6 due · 3 new", "4 new", "All caught up". "Due" is learning plus
 * review; new cards are counted apart, since the learner hasn't seen them yet. Returns null
 * when the deck has no `due_counts`, and the caller renders nothing.
 */
export function describeDueCounts(dueCounts) {
  if (!dueCounts) return null;

  const due = dueCounts.learning + dueCounts.review;
  const parts = [];
  if (due > 0) parts.push(`${due} due`);
  if (dueCounts.new > 0) parts.push(`${dueCounts.new} new`);
  return parts.length ? parts.join(' · ') : 'All caught up';
}
