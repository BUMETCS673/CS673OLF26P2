/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   API client development
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { useMemo } from 'react';
import { useAuth } from '../auth/AuthContext';
import { createAuthenticatedGenerateApi } from './generate.client.js';

export function useGenerateApi() {
  const { expireSession } = useAuth();
  return useMemo(() => createAuthenticatedGenerateApi(expireSession), [expireSession]);
}
