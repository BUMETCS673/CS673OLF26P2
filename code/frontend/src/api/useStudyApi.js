import { useMemo } from 'react';
import { useAuth } from '../auth/AuthContext';
import { createAuthenticatedStudyApi } from './study.client.js';

export function useStudyApi() {
  const { expireSession } = useAuth();
  return useMemo(() => createAuthenticatedStudyApi(expireSession), [expireSession]);
}
