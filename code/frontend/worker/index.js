// Cloudflare serves the built files in dist/ itself. This Worker only runs for the paths
// that run_worker_first in wrangler.jsonc lists, and forwards the API and OAuth ones to the
// backend. The browser only ever sees this site, so there's no CORS to set up and the session
// cookie is sent on every API call (decision D4).
//
// A sleeping backend answers with a 429 that the Worker turns into a 503 while GitHub's wake
// workflow starts it.

// The backend's paths: the API, plus the MCP server's OAuth endpoints and discovery files,
// which the SDK serves at fixed root paths
const PROXIED = /^\/(api\/|(authorize|token|register|revoke)$|\.well-known\/oauth-[a-z-]+(\/.*)?$)/;

const WAKE_WORKFLOW = 'wake.yml';
const WAKE_REF = 'develop'; // the default branch, where workflow_dispatch reads the workflow
const WAKE_COOLDOWN_MS = 2 * 60_000;

// Per isolate since the Cache API does nothing on workers.dev
// wake.yml's concurrency group drops the extra runs from other isolates
let wakeStartedAt = 0;

async function startWake(env) {
  let status;
  try {
    const response = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${WAKE_WORKFLOW}/dispatches`,
      {
        method: 'POST',
        headers: {
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${env.GITHUB_WAKE_TOKEN}`,
          'User-Agent': 'cadence-worker', // GitHub's API rejects requests without one
          'X-GitHub-Api-Version': '2022-11-28',
        },
        body: JSON.stringify({ ref: WAKE_REF }),
      },
    );
    if (response.ok) {
      return;
    }
    status = response.status;
  } catch (error) {
    status = error.name;
  }
  wakeStartedAt = 0; // the next request tries again
  console.error(`wake dispatch failed with ${status}`);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Step 1: send anything that isn't a proxied path back to the static files
    // the run_worker_first globs are looser than PROXIED, so /tokens still reaches the React app
    if (!PROXIED.test(url.pathname)) {
      return env.ASSETS.fetch(request);
    }

    // Step 2: copy the request onto the backend's address
    const target = new URL(url.pathname + url.search, env.API_ORIGIN);
    const forwarded = new Request(target, request); // same method, headers and streamed body
    forwarded.headers.delete('Host'); // the URL sets it, and Render picks the service by Host
    // Cloudflare's own header, replacing whatever the caller sent, since the backend's rate
    // limit trusts the first X-Forwarded-For entry
    const caller = request.headers.get('CF-Connecting-IP');
    if (caller) {
      forwarded.headers.set('X-Forwarded-For', caller);
    } else {
      forwarded.headers.delete('X-Forwarded-For');
    }
    forwarded.headers.set('X-Forwarded-Proto', url.protocol.slice(0, -1));

    // Step 3: send it and give redirects back to the browser rather than following them here
    // OAuth's authorize step has to send the browser itself on to the client's redirect URI
    const response = await fetch(forwarded, { redirect: 'manual' });

    // Step 4: start the wake workflow when Render says the backend is asleep
    // a plain text 503 is what the frontend retries
    if (response.status === 429 && response.headers.get('x-render-routing')?.startsWith('hibernate')) {
      if (env.GITHUB_WAKE_TOKEN && Date.now() - wakeStartedAt > WAKE_COOLDOWN_MS) {
        wakeStartedAt = Date.now();
        ctx.waitUntil(startWake(env)); // runs after the response is sent
      }
      return new Response('Backend is waking up', {
        status: 503,
        headers: { 'Content-Type': 'text/plain', 'Retry-After': '5' },
      });
    }

    // Step 5: point redirects aimed at the backend back at this site
    const location = response.headers.get('Location');
    if (location?.startsWith(target.origin)) {
      const rewritten = new Response(response.body, response); // same status, headers and stream
      rewritten.headers.set('Location', url.origin + location.slice(target.origin.length));
      return rewritten;
    }
    return response; // passed straight through, so job events stream as they arrive
  },
};
