// F4: describeSchedule() and describeDueCounts(). One test per row of their tables under
// "Frontend contracts" in code/plans/FINALIZE_ITERATION_2_PLAN.md.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F4 in the plan), direction, and review by Nurzat Mukhamedali.

import { expect, test } from 'vitest';
import { describeDueCounts, describeSchedule } from '../src/study/describeSchedule.js';

// A fixed clock, so the labels don't depend on when the test runs.
const NOW = Date.parse('2026-10-01T14:00:00Z');
const at = (seconds) => new Date(NOW + seconds * 1000).toISOString();
const MINUTE = 60;
const DAY = 86_400;

test.each([
  ['a new card', { state: 'new', due_at: null }, 'New'],
  ['learning, due 2 minutes ago', { state: 'learning', due_at: at(-2 * MINUTE) }, 'Learning · due now'],
  ['learning, due in 330 seconds', { state: 'learning', due_at: at(330) }, 'Learning · in 6m'],
  ['relearning, due in 10 minutes', { state: 'relearning', due_at: at(10 * MINUTE) }, 'Relearning · in 10m'],
  ['review, due 3 days ago', { state: 'review', due_at: at(-3 * DAY) }, 'Review · due now'],
  ['review, due in 25 days', { state: 'review', due_at: at(25 * DAY) }, 'Review · in 25d'],
])('describeSchedule: %s', (_, card, expected) => {
  expect(describeSchedule(card, NOW)).toBe(expected);
});

test.each([
  ['undefined (B2 not merged yet)', undefined, null],
  ['some due and some new', { learning: 3, review: 3, new: 3 }, '6 due · 3 new'],
  ['only new', { learning: 0, review: 0, new: 4 }, '4 new'],
  ['only due', { learning: 1, review: 2, new: 0 }, '3 due'],
  ['all zero', { learning: 0, review: 0, new: 0 }, 'All caught up'],
])('describeDueCounts: %s', (_, dueCounts, expected) => {
  expect(describeDueCounts(dueCounts)).toBe(expected);
});
