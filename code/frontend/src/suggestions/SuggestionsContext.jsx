import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { createProblemCardsApi } from '../api/problemCards.js';
import { useApi } from '../api/useApi.js';
import { useAuth } from '../auth/AuthContext';

// A review's job waits 10 minutes to gather cards, so this outlasts that and the run itself. A
// review waiting on budget takes hours, so polling then stops until a page change or tab return.
export const POLL_MS = 30_000;
export const MAX_POLLS = 30;  // 15 minutes

const EMPTY = { processing: false, ready: [] };
const noop = () => {};

// The defaults let a page render on its own, as in tests, with no suggestions.
export const SuggestionsContext = createContext({
  ...EMPTY,
  notice: null,
  studying: false,
  refresh: noop,
  dismissNotice: noop,
  setSessionDone: noop,
});

export const useSuggestions = () => useContext(SuggestionsContext);

/**
 * One shared store for Problem Cards suggestions, so the notice, the home card and the deck banner
 * always agree and update without a page reload.
 *
 * Checks only read. They run on page changes and tab returns, and every POLL_MS while a review is
 * on its way, but not during a study session, so nothing interrupts it.
 */
export function SuggestionsProvider({ children }) {
  const { user } = useAuth();
  const api = useApi(createProblemCardsApi);
  const { pathname } = useLocation();
  const userId = user?.id;
  const [loaded, setLoaded] = useState({ ...EMPTY, owner: null });
  // Results belong to whoever they were loaded for, so a new sign-in can't see the last user's.
  const data = loaded.owner === userId ? loaded : EMPTY;
  const [notice, setNotice] = useState(null);
  const [sessionDone, setSessionDone] = useState(false);
  // Review ids from the last check. Null until the first check, whose results get no notice:
  // they were ready before this visit, so the home card shows them.
  const known = useRef(null);
  const studying = pathname.endsWith('/study') && !sessionDone;

  const refresh = useCallback(async () => {
    try {
      const next = await api.getSuggestions();
      const ready = next.ready ?? [];
      if (known.current !== null) {
        const arrived = ready.find((item) => !known.current.has(item.review_id));
        if (arrived) setNotice(arrived);
      }
      known.current = new Set(ready.map((item) => item.review_id));
      setLoaded({ processing: Boolean(next.processing), ready, owner: userId });
    } catch {
      // Suggestions are optional, so a failed check leaves the page as it is.
    }
  }, [api, userId]);

  // Before the check below, so a new sign-in's first results don't trigger a notice.
  useEffect(() => {
    known.current = null;
  }, [userId]);

  useEffect(() => {
    if (user && !studying) refresh();
  }, [user, studying, pathname, refresh]);

  useEffect(() => {
    if (!user || studying) return undefined;
    const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [user, studying, refresh]);

  useEffect(() => {
    // No checks during a session, so a notice can't appear in the middle of studying.
    if (!data.processing || !user || studying) return undefined;
    let polls = 0;
    const timer = setInterval(() => {
      polls += 1;
      if (polls >= MAX_POLLS) clearInterval(timer);
      refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [data.processing, user, studying, refresh]);

  const dismissNotice = useCallback(() => setNotice(null), []);
  const { processing, ready } = data;
  const value = useMemo(
    () => ({ processing, ready, notice, studying, refresh, dismissNotice, setSessionDone }),
    [processing, ready, notice, studying, refresh, dismissNotice],
  );
  return <SuggestionsContext.Provider value={value}>{children}</SuggestionsContext.Provider>;
}
