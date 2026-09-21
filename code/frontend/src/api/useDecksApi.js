import { useMemo } from 'react';
import { useAuth } from '../auth/AuthContext';
import { createAuthenticatedDecksApi } from './decks.client.js';

export function useDecksApi() {
  const { expireSession } = useAuth();
  return useMemo(() => createAuthenticatedDecksApi(expireSession), [expireSession]);
}
