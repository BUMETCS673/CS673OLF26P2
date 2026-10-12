// F4: normalizeAnswer() and checkTypedAnswer(). One test per row of C8's examples table in
// code/plans/ITERATION_3_PLAN.md, plus one for each normalization step on its own.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Devin (Cognition AI)
// AI-Assisted Activities:
//   Unit test creation
// Human role: acceptance examples (F4 in the plan), direction, and review by Nurzat Mukhamedali.

import { expect, test } from 'vitest';
import { checkTypedAnswer, normalizeAnswer } from '../src/study/typedAnswer.js';

const COMPOSED_CAFE = 'caf\u00e9';
const DECOMPOSED_CAFE = 'cafe\u0301';

const CORRECT = { verdict: 'correct', suggestedRating: 'good' };
const INCORRECT = { verdict: 'incorrect', suggestedRating: 'again' };

test.each([
  ['case and end punctuation are ignored', 'the library', 'The Library.', CORRECT],
  ['extra spaces are ignored', 'the library', '  the   library ', CORRECT],
  ['leading and trailing marks are ignored', 'dónde está', '¿Dónde está?', CORRECT],
  ['NFC: a composed é equals e + combining accent', COMPOSED_CAFE, DECOMPOSED_CAFE, CORRECT],
  ['spelling counts', 'receive', 'recieve', INCORRECT],
  ['accents are part of the spelling', 'adiós', 'adios', INCORRECT],
  ['a different number is wrong', '1945', '1946', INCORRECT],
  ['inner punctuation stays', '3.14', '314', INCORRECT],
  ['# is not stripped', 'C#', 'C', INCORRECT],
  ['blank means "I don\'t know"', 'anything', '', INCORRECT],
  ['"?" alone means "I don\'t know"', 'anything', '?', INCORRECT],
])('%s: expected %j, typed %j', (_why, expected, typed, result) => {
  expect(checkTypedAnswer(expected, typed)).toEqual(result);
});

test('step 1: NFC joins a letter and its combining accent into one code point', () => {
  expect(normalizeAnswer(DECOMPOSED_CAFE)).toBe(COMPOSED_CAFE);
  expect(normalizeAnswer(DECOMPOSED_CAFE)).toHaveLength(4);
});

test('step 2: lowercase', () => {
  expect(normalizeAnswer('El AEROPUERTO')).toBe('el aeropuerto');
});

test('step 3: every run of whitespace, tabs and newlines included, becomes one space', () => {
  expect(normalizeAnswer('la\t\tbiblioteca \n  central')).toBe('la biblioteca central');
});

test('step 4: whitespace and the listed marks go from both ends, however many there are', () => {
  expect(normalizeAnswer(' ¡¿«(“‘"\'[{hola}]\'"’”)»?!… .,;: ')).toBe('hola');
});

test('nothing else is removed: inner marks, accents, and # + - $ stay', () => {
  expect(normalizeAnswer('¿qué tal, amigo?')).toBe('qué tal, amigo');
  expect(normalizeAnswer('C++')).toBe('c++');
  expect(normalizeAnswer('-$5')).toBe('-$5');
  expect(normalizeAnswer('#1')).toBe('#1');
});

test('a typed answer that is only whitespace is incorrect, even against a blank expected answer', () => {
  expect(checkTypedAnswer('', '   ')).toEqual(INCORRECT);
});
