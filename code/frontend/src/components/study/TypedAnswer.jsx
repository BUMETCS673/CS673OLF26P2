/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Devin (Cognition AI)
 * AI-Assisted Activities:
 *   UI component development
 *   Documentation
 * Human role: requirements (F6 in code/plans/ITERATION_3_PLAN.md), direction, and review by
 * Nurzat Mukhamedali.
 */

import { useId, useState } from 'react';

/**
 * Typed mode's answer box (Iteration 3, F6), as C9 in code/plans/ITERATION_3_PLAN.md says.
 *
 * props:
 *   answer    the reducer's graded answer, { typed, verdict, suggestedRating }, or null
 *   disabled  boolean
 *   onSubmit  (typed) => void, with the raw text, on Enter or Check
 *
 * Before grading it's a form; after, the typed answer and the verdict. The form is its own
 * component, so every new card (even the same card again) starts with an empty box.
 */
export default function TypedAnswer({ answer, disabled, onSubmit }) {
  if (!answer) return <TypedAnswerForm disabled={disabled} onSubmit={onSubmit} />;

  const correct = answer.verdict === 'correct';
  return <div className="typed-answer typed-answer-graded">
    <p className={`typed-verdict ${correct ? 'correct' : 'incorrect'}`}>{correct ? 'Correct' : 'Incorrect'}</p>
    <p className="typed-typed">
      {answer.typed.trim() ? `You typed: ${answer.typed}` : 'You typed nothing'}
    </p>
  </div>;
}

function TypedAnswerForm({ disabled, onSubmit }) {
  const id = useId();
  const [text, setText] = useState('');

  function submit(event) {
    event.preventDefault();
    onSubmit(text);
  }

  // Autocorrect and spellcheck are off: the learner is being tested on the spelling.
  return <form className="typed-answer" onSubmit={submit}>
    <label htmlFor={id}>Your answer</label>
    <div className="typed-answer-row">
      <input id={id} className="typed-answer-input" type="text" value={text} disabled={disabled}
        onChange={(event) => setText(event.target.value)} autoFocus
        autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} />
      <button type="submit" className="button primary" disabled={disabled}>Check</button>
    </div>
  </form>;
}
