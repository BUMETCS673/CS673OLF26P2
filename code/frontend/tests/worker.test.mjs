import { afterEach, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import worker from '../worker/index.js';

const BACKEND = 'https://backend.example';
const SITE = 'https://app.example';

// Stands in for Cloudflare's static files and records what reached them
function makeEnv() {
  const assets = [];
  return {
    assets,
    env: {
      API_ORIGIN: BACKEND,
      ASSETS: { fetch: async (request) => { assets.push(new URL(request.url).pathname); return new Response('index'); } },
    },
  };
}

// Replaces the global fetch, keeping each forwarded request and its options
function stubBackend(response = () => new Response('{"ok":true}')) {
  const sent = [];
  vi.stubGlobal('fetch', async (request, options) => { sent.push({ request, options }); return response(); });
  return sent;
}

afterEach(() => vi.unstubAllGlobals());

test('an API call goes to the backend with the same path, query, method, cookie and body', async () => {
  const sent = stubBackend();
  const { env } = makeEnv();
  await worker.fetch(new Request(`${SITE}/api/materials?page=2`, {
    method: 'POST', headers: { Cookie: 'session=abc' }, body: 'hello',
  }), env);

  const [{ request, options }] = sent;
  assert.equal(request.url, `${BACKEND}/api/materials?page=2`);
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.get('Cookie'), 'session=abc');
  assert.equal(await request.text(), 'hello');
  assert.equal(request.headers.get('Host'), null);
  assert.equal(request.headers.get('X-Forwarded-Proto'), 'https');
  assert.deepEqual(options, { redirect: 'manual' });
});

test('the OAuth endpoints and discovery files are forwarded too', async () => {
  const sent = stubBackend();
  const { env } = makeEnv();
  for (const path of ['/authorize?client_id=x', '/token', '/register', '/revoke',
    '/.well-known/oauth-authorization-server', '/.well-known/oauth-protected-resource/api/mcp']) {
    await worker.fetch(new Request(SITE + path), env);
  }
  assert.equal(sent.length, 6);
});

test('paths the globs catch that aren\'t backend paths get the static files', async () => {
  const sent = stubBackend();
  const { env, assets } = makeEnv();
  for (const path of ['/tokens', '/register-now', '/.well-known/oauth-', '/api']) {
    const response = await worker.fetch(new Request(SITE + path), env);
    assert.equal(await response.text(), 'index');
  }
  assert.equal(sent.length, 0);
  assert.deepEqual(assets, ['/tokens', '/register-now', '/.well-known/oauth-', '/api']);
});

test("the caller's address comes from Cloudflare, not from a header they sent", async () => {
  const sent = stubBackend();
  const { env } = makeEnv();
  await worker.fetch(new Request(`${SITE}/api/decks`, {
    headers: { 'CF-Connecting-IP': '203.0.113.7', 'X-Forwarded-For': '6.6.6.6' },
  }), env);
  await worker.fetch(new Request(`${SITE}/api/decks`, { headers: { 'X-Forwarded-For': '6.6.6.6' } }), env);

  assert.equal(sent[0].request.headers.get('X-Forwarded-For'), '203.0.113.7');
  assert.equal(sent[1].request.headers.get('X-Forwarded-For'), null);
});

test('a redirect to the backend is pointed back at this site', async () => {
  stubBackend(() => new Response(null, {
    status: 307, headers: { Location: `${BACKEND}/api/decks/?page=2`, 'X-Request-Id': 'r1' },
  }));
  const { env } = makeEnv();
  const response = await worker.fetch(new Request(`${SITE}/api/decks?page=2`), env);

  assert.equal(response.status, 307);
  assert.equal(response.headers.get('Location'), `${SITE}/api/decks/?page=2`);
  assert.equal(response.headers.get('X-Request-Id'), 'r1');
});

test('a redirect elsewhere, like OAuth sending the browser to a client, is left alone', async () => {
  const location = 'http://localhost:33418/callback?code=xyz';
  stubBackend(() => new Response(null, { status: 302, headers: { Location: location } }));
  const { env } = makeEnv();
  const response = await worker.fetch(new Request(`${SITE}/authorize?client_id=x`), env);

  assert.equal(response.status, 302);
  assert.equal(response.headers.get('Location'), location);
});

test("the backend's response is returned as is, so a stream isn't buffered", async () => {
  const backendResponse = new Response('data: {"status":"running"}\n\n', {
    headers: { 'Content-Type': 'text/event-stream' },
  });
  stubBackend(() => backendResponse);
  const { env } = makeEnv();
  const response = await worker.fetch(new Request(`${SITE}/api/jobs/4/events`), env);

  assert.equal(response, backendResponse);
});
