/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Shared constants
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/**
 * Shared by the study session and the typed-answer check (Lab 3, Step 0b).
 */

/** The four rating buttons, spelled exactly as the review endpoint expects them. */
export const RATINGS = ['again', 'hard', 'good', 'easy'];

/**
 * How early a learning card may be shown when nothing else is left to study: Anki's
 * "learn ahead limit". Mirrors LEARN_AHEAD in backend/app/scheduler.py -- change both
 * together.
 */
export const LEARN_AHEAD_MS = 20 * 60 * 1000;
