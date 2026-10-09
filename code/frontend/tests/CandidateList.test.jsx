// @vitest-environment jsdom
//
// Step 0b's placeholder test. F2 takes this file over, with its acceptance examples.
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import CandidateList from '../src/components/generate/CandidateList.jsx';

afterEach(cleanup);

test('the placeholder renders with the props C7 promises', () => {
  const generation = {
    id: 7, deck_id: 2, mode: 'prompt', requested_count: 1, model: 'fake',
    created_at: '2026-10-09T14:00:00Z',
    cards: [{ index: 0, front: 'Sample question 1', back: 'Sample answer 1', status: 'pending' }],
  };
  render(<CandidateList generation={generation} busy={false} error={null} onAccept={vi.fn()}
    onReject={vi.fn()} onGenerateMore={vi.fn()} onBackToDeck={vi.fn()} />);

  expect(screen.getByText('The review list arrives in F2')).toBeTruthy();
});
