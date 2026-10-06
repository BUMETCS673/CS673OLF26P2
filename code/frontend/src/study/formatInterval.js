/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Utility function development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/**
 * The short label under a rating button: "<1m", "6m", "1d", "1.5mo", "100y" (Iteration 2,
 * Step 0b). The backend sends intervals in seconds; this only formats them, and never works
 * one out (rule 6 in code/plans/LAB_3_PLAN.md).
 *
 * Each unit is rounded, and a value that rounds up to the next unit moves up to it: 59.5
 * minutes is "1h", not "60m". A month is 30 days and a year 365. Months and years keep one
 * decimal place, dropped when it's ".0".
 */

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

/** `value` rounded to one decimal place: 1.53 -> 1.5, 2.04 -> 2. */
const oneDecimal = (value) => Math.round(value * 10) / 10;

export function formatInterval(seconds) {
  if (seconds < MINUTE) return '<1m';

  const minutes = Math.round(seconds / MINUTE);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.round(seconds / HOUR);
  if (hours < 24) return `${hours}h`;

  const days = Math.round(seconds / DAY);
  if (days < 30) return `${days}d`;

  const months = oneDecimal(seconds / MONTH);
  if (months < 12) return `${months}mo`;

  return `${oneDecimal(seconds / YEAR)}y`;
}
