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
