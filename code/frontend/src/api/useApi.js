/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useMemo } from 'react';
import { useAuth } from '../auth/AuthContext';
import { createAuthenticatedApi } from './request.js';

// One API client per page, signed out on a 401. Pass a module-level factory such as
// createDecksApi, so the memo stays stable across renders.
export function useApi(createApi) {
  const { expireSession } = useAuth();
  return useMemo(() => createAuthenticatedApi(createApi, expireSession), [createApi, expireSession]);
}
