// Cloudflare serves the built files in dist/ itself. This Worker only runs for the paths
// that run_worker_first in wrangler.jsonc lists, and forwards the API and OAuth ones to the
// backend. The browser only ever sees this site, so there's no CORS to set up and the session
// cookie is sent on every API call (decision D4).
//
// The backend sees these requests coming from outside Render, so a sleeping free-tier backend
// wakes up on the first one. The request just waits through the cold start.

// The backend's paths: the API, plus the MCP server's OAuth endpoints and discovery files,
// which the SDK serves at fixed root paths
const PROXIED = /^\/(api\/|(authorize|token|register|revoke)$|\.well-known\/oauth-[a-z-]+(\/.*)?$)/;

export default {
  async fetch(request, env) {
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

    // Step 4: point redirects aimed at the backend back at this site
    const location = response.headers.get('Location');
    if (location?.startsWith(target.origin)) {
      const rewritten = new Response(response.body, response); // same status, headers and stream
      rewritten.headers.set('Location', url.origin + location.slice(target.origin.length));
      return rewritten;
    }
    return response; // passed straight through, so job events stream as they arrive
  },
};
