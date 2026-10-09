// @vitest-environment jsdom
//
// Step 0b's placeholder test. F1 takes this file over, with its acceptance examples.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import GenerateForm from '../src/components/generate/GenerateForm.jsx';

afterEach(cleanup);

test('the placeholder renders with the props C7 promises', () => {
  const deck = { id: 2, name: 'Travel Spanish', description: null, card_count: 11 };
  render(<GenerateForm deck={deck} cardCount={11} busy={false} error={null} onGenerate={vi.fn()} />);

  expect(screen.getByText('The form arrives in F1')).toBeTruthy();
});
