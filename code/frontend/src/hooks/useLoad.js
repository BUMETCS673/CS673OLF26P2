/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Refactoring
 * Human role: plan approval and code review by Duc Anh Nguyen.
 */

import { useCallback, useEffect, useState } from 'react';

/**
 * Runs `load` when the page mounts and again on reload(), and keeps the answer.
 *
 * The result is tagged with the load function and revision it answers, so `loading` is
 * derived instead of being switched on at the top of the effect. A synchronous setState
 * there costs an extra render pass on every reload, which is what
 * react-hooks/set-state-in-effect flags. A late answer to an older load is ignored.
 *
 * load      () => Promise. Wrap it in useCallback; a new function means a new load.
 * returns   { data, error, loading, revision, reload, setData }
 *           revision counts reloads, for keying a child that should start over.
 *           setData(value | (data) => value) edits the loaded data in place.
 */
export function useLoad(load) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ load: null, revision: -1, data: undefined, error: null });
  const loading = result.load !== load || result.revision !== revision;

  useEffect(() => {
    let active = true;
    load().then(
      (data) => { if (active) setResult({ load, revision, data, error: null }); },
      (error) => { if (active) setResult({ load, revision, data: undefined, error }); },
    );
    return () => { active = false; };
  }, [load, revision]);

  const reload = useCallback(() => setRevision((count) => count + 1), []);
  const setData = useCallback((update) => setResult((current) => ({
    ...current,
    data: typeof update === 'function' ? update(current.data) : update,
  })), []);

  return { data: result.data, error: result.error, loading, revision, reload, setData };
}
