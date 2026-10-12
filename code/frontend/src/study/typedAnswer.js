/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   Answer-checking logic
 *   Documentation
 * Human role: requirements (F4 in code/plans/ITERATION_3_PLAN.md), direction, and review by
 * Nurzat Mukhamedali.
 */

/**
 * The typed-answer check (Iteration 3, F4), as C8 in code/plans/ITERATION_3_PLAN.md
 * describes it. Pure (rule 9): no React and no API. normalize_front() in
 * backend/app/ai/cleanup.py implements the same rule (rule 22) -- change both together.
 */

import { RATINGS } from './constants.js';

const [AGAIN, , GOOD] = RATINGS;

/** Whitespace and the marks that step 4 removes from both ends. */
const END_MARKS = /^[\s.,;:!?¿¡…'"‘’“”«»()[\]{}]+|[\s.,;:!?¿¡…'"‘’“”«»()[\]{}]+$/gu;

/** NFC, lowercase, one space for each run of whitespace, then the end marks removed. */
export function normalizeAnswer(text) {
  return text.normalize('NFC').toLowerCase().replace(/\s+/gu, ' ').replace(END_MARKS, '');
}

/**
 * Whether `typed` matches the card's answer, `expected`, after normalizing both. A blank
 * typed answer means "I don't know", so it's always incorrect.
 *
 * Returns { verdict: 'correct' | 'incorrect', suggestedRating: 'good' | 'again' }.
 */
export function checkTypedAnswer(expected, typed) {
  const answer = normalizeAnswer(typed);
  const correct = answer !== '' && answer === normalizeAnswer(expected);
  return correct
    ? { verdict: 'correct', suggestedRating: GOOD }
    : { verdict: 'incorrect', suggestedRating: AGAIN };
}
