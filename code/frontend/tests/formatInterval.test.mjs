import { test } from 'vitest';
import assert from 'node:assert/strict';
import { formatInterval } from '../src/study/formatInterval.js';

const DAY = 24 * 60 * 60;

// One test per row of the table in "Frontend contracts" in
// code/plans/FINALIZE_ITERATION_2_PLAN.md.

test('under a minute is <1m: 0 and 59 seconds', () => {
  assert.equal(formatInterval(0), '<1m');
  assert.equal(formatInterval(59), '<1m');
});

test('60 seconds is 1m', () => {
  assert.equal(formatInterval(60), '1m');
});

test('330 seconds is 6m: 5.5 minutes rounds up', () => {
  assert.equal(formatInterval(330), '6m');
});

test('600 and 900 seconds are 10m and 15m', () => {
  assert.equal(formatInterval(600), '10m');
  assert.equal(formatInterval(900), '15m');
});

test('3570 seconds is 1h: 59.5 minutes rounds to 60, which is an hour', () => {
  assert.equal(formatInterval(3570), '1h');
});

test('3600 seconds is 1h', () => {
  assert.equal(formatInterval(3600), '1h');
});

test('86400 and 345600 seconds are 1d and 4d', () => {
  assert.equal(formatInterval(86400), '1d');
  assert.equal(formatInterval(345600), '4d');
});

test('25 days is 25d', () => {
  assert.equal(formatInterval(25 * DAY), '25d');
});

test('30 days is 1mo: a month is 30 days', () => {
  assert.equal(formatInterval(30 * DAY), '1mo');
});

test('45 and 238 days are 1.5mo and 7.9mo: one decimal place, dropped when it is .0', () => {
  assert.equal(formatInterval(45 * DAY), '1.5mo');
  assert.equal(formatInterval(238 * DAY), '7.9mo');
  assert.equal(formatInterval(60 * DAY), '2mo');
});

test('365 days is 1y: a year is 365 days', () => {
  assert.equal(formatInterval(365 * DAY), '1y');
});

test('476 and 36500 days are 1.3y and 100y', () => {
  assert.equal(formatInterval(476 * DAY), '1.3y');
  assert.equal(formatInterval(36500 * DAY), '100y');
});
