import { ApiError } from './client.js';
import { pathId as id } from './request.js';

const FINISHED = new Set(['done', 'failed']);
const POLL_MS = 2000;
const POLL_ATTEMPTS = 450; // 15 minutes, so a stuck job can't keep a page polling forever

const unavailable = () => new ApiError(
  0,
  'job_unavailable',
  "We couldn't follow this job. Please try again.",
);
const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

// Follows a background job until it finishes, and resolves with its last event: { status, result,
// error, progress }. A browser reconnects by itself after a dropped connection, and also after the
// server closes the stream, so this closes it as soon as the job is finished. `onProgress` hears
// every earlier event. Aborting `signal` closes the stream, and the promise never settles, since
// whoever aborted has stopped listening. EventSource can be replaced so that this can be tested
// without a browser.
export function followJob(
  jobId,
  { onProgress, signal, EventSourceClass = globalThis.EventSource } = {},
) {
  return new Promise((resolve, reject) => {
    // Without EventSource, callers fall back to polling, the same as for a blocked stream.
    if (!EventSourceClass) {
      reject(unavailable());
      return;
    }
    const source = new EventSourceClass(`/api/jobs/${id(jobId)}/events`);
    signal?.addEventListener('abort', () => source.close());

    source.addEventListener('status', (message) => {
      const event = JSON.parse(message.data);
      if (FINISHED.has(event.status)) {
        source.close();
        resolve(event);
      } else {
        onProgress?.(event);
      }
    });

    // While it's reconnecting, its state is CONNECTING. CLOSED means it has given up, as it does
    // for a 401 or a 404.
    source.onerror = () => {
      if (source.readyState === EventSourceClass.CLOSED) {
        source.close();
        reject(unavailable());
      }
    };
  });
}

// For when the event stream can't be used, such as behind a proxy that blocks it. It goes through
// `request`, so unlike a stream it hears a 401, and an expired session signs the learner out.
export async function pollJob(jobId, request, wait = sleep) {
  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    const job = await request(`/api/jobs/${id(jobId)}`);
    if (FINISHED.has(job.status)) return job;
    await wait(POLL_MS);
  }
  throw unavailable();
}
