// @vitest-environment jsdom
//
// AI Utilization: ~100% of this file's code
// AI Tools Used: Claude Code (Claude Opus 5.5)
// AI-Assisted Activities:
//   Unit test creation
// Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import { afterEach, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import AiBadge from '../src/components/AiBadge.jsx';

afterEach(cleanup);

test('the badge reads AI-generated, and its title says who wrote and who accepted the card', () => {
  render(<AiBadge />);

  const badge = screen.getByText('AI-generated');
  expect(badge.title).toBe('Written by AI (Google Gemini) and accepted by you');
  expect(badge.className).toBe('badge badge-ai');
});
