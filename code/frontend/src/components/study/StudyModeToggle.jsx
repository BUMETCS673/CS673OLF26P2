/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: requirements (F5 in code/plans/ITERATION_3_PLAN.md), direction, and review by
 * Nurzat Mukhamedali.
 */

import { useId } from 'react';

const MODES = [['flashcard', 'Flashcard'], ['typed', 'Typed answer']];

/**
 * The study page's Flashcard / Typed answer switch (Iteration 3, F5): two radios in a
 * fieldset with a visually hidden "Study mode" legend, drawn as a segmented control.
 *
 * props:
 *   mode      'flashcard' | 'typed': the checked one
 *   onChange  (mode) => void, called once when the other one is chosen
 */
export default function StudyModeToggle({ mode, onChange }) {
  const id = useId();
  return <fieldset className="study-mode-toggle">
    <legend className="sr-only">Study mode</legend>
    {MODES.map(([value, label]) => <label key={value} className="study-mode">
      <input type="radio" name={`${id}-mode`} value={value} checked={mode === value}
        onChange={() => onChange(value)} />
      <span>{label}</span>
    </label>)}
  </fieldset>;
}
