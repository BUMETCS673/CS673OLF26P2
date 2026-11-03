import { useCallback, useEffect, useRef, useState } from 'react';
import { followJob } from '../api/jobs.js';

export const POLL_MS = 2000;
export const MAX_POLL_FAILURES = 3; // a dropped connection shouldn't end a long job's progress

const PROCESSING = 'processing';

/** What to show while a file is uploading or processing, or '' when it's neither. */
export function progressMessage(uploading, material) {
  if (uploading) return 'Uploading your file…';
  if (material?.status !== PROCESSING) return '';
  if (material.stage === 'reading') return 'Reading your file…';
  if (material.stage === 'screening') return 'Checking your file…';
  if (material.stage === 'finding_topics') return 'Finding topics…';
  // No count here: this goes in a status region, and a screen reader would read out every update.
  if (material.stage === 'embedding') return 'Saving your materials…';
  return 'Waiting to start…';
}

/**
 * Uploads one file and follows it until it's ready or failed.
 *
 * Progress comes live from the file's job. Polling takes over if the stream can't be used, as can
 * happen behind some proxies, because a file can take minutes and shouldn't look stuck.
 *
 * `api` is a createMaterialsApi client, and `follow` can replace followJob in tests. Returns:
 *   upload(file)  starts over with a new file
 *   reset()       forgets the file, and any response still on its way
 *   uploading     the request itself is running
 *   material      the server's Document, or null
 *   error         an ApiError from the upload or from polling, or null
 */
export function useMaterialUpload(api, follow = followJob) {
  const [uploading, setUploading] = useState(false);
  const [material, setMaterial] = useState(null);
  const [error, setError] = useState(null);
  // Each upload and reset gets a number, so a slow answer can't overwrite a later choice.
  const latestUpload = useRef(0);

  const reset = useCallback(() => {
    latestUpload.current += 1;
    setUploading(false);
    setMaterial(null);
    setError(null);
  }, []);

  const upload = useCallback(async (file) => {
    const attempt = ++latestUpload.current;
    setUploading(true);
    setMaterial(null);
    setError(null);
    try {
      const uploaded = await api.upload(file);
      if (attempt === latestUpload.current) setMaterial(uploaded);
    } catch (failure) {
      if (attempt === latestUpload.current) setError(failure);
    } finally {
      if (attempt === latestUpload.current) setUploading(false);
    }
  }, [api]);

  // Only these ids restart the effect, so progress updates don't reset the timer or the stream.
  const processingId = material?.status === PROCESSING ? material.id : null;
  const jobId = processingId === null ? null : material.job_id;

  useEffect(() => {
    if (processingId === null) return undefined;
    let stopped = false;
    let timer;
    let failures = 0;
    const stream = new AbortController();

    async function poll() {
      if (stopped) return;
      try {
        const next = await api.getMaterial(processingId);
        if (stopped) return;
        failures = 0;
        setMaterial(next);
      } catch (failure) {
        if (stopped) return;
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          setError(failure);
          return;
        }
      }
      timer = setTimeout(poll, POLL_MS);
    }

    if (jobId == null) {
      timer = setTimeout(poll, POLL_MS);
    } else {
      const onProgress = ({ progress }) => {
        if (!stopped && progress) setMaterial((current) => ({ ...current, ...progress }));
      };
      // The document has the final say either way, including on what a failed job left behind.
      follow(jobId, { onProgress, signal: stream.signal }).then(poll, poll);
    }
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream.abort();
    };
  }, [api, follow, processingId, jobId]);

  return { upload, reset, uploading, material, error };
}
