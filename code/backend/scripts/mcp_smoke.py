"""Smoke tests for the live MCP server and its OAuth endpoints.

Usage: python scripts/mcp_smoke.py https://your-site.onrender.com

Read-only by default. Set MCP_TOKEN to a personal access token to also list tools and call
whoami. Uses only the standard library so it runs anywhere, CI included.
"""

import json
import os
import sys
import urllib.error
import urllib.request

TOOLS = {"whoami", "list_decks", "get_due_cards", "search_knowledge", "add_cards", "generate_cards",
         "get_job"}
ACCEPT = "application/json, text/event-stream"  # Streamable HTTP needs both
failures = 0


def request(method, url, body=None, headers=None):
    """Status, headers and body. Error statuses are answers here, not exceptions."""
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode()


def check(name, ok, detail=""):
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def as_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}


def main(base):
    # Step 1: the app is up
    status, _, _ = request("GET", f"{base}/api/health")
    check("health is 200", status == 200, status)

    # Step 2: the discovery documents name this site, so clients sign in here and nowhere else
    status, _, text = request("GET", f"{base}/.well-known/oauth-protected-resource/api/mcp")
    resource = as_json(text)
    check("resource metadata is JSON", status == 200 and bool(resource), f"{status} {text[:80]}")
    check("resource is this site's /api/mcp", resource.get("resource") == f"{base}/api/mcp",
          resource.get("resource"))
    check("authorization server is this site", resource.get("authorization_servers") == [base],
          resource.get("authorization_servers"))

    status, _, text = request("GET", f"{base}/.well-known/oauth-authorization-server")
    server = as_json(text)
    check("server metadata is JSON", status == 200 and bool(server), f"{status} {text[:80]}")
    check("issuer is this site", server.get("issuer") == base, server.get("issuer"))
    for field, path in [("authorization_endpoint", "/authorize"), ("token_endpoint", "/token"),
                        ("registration_endpoint", "/register"), ("revocation_endpoint", "/revoke")]:
        check(f"{field} is {path} here", server.get(field) == base + path, server.get(field))
    check("PKCE S256 is required", server.get("code_challenge_methods_supported") == ["S256"],
          server.get("code_challenge_methods_supported"))

    # Step 3: the MCP endpoint refuses callers without a working token
    headers = {"Content-Type": "application/json", "Accept": ACCEPT}
    status, reply_headers, _ = request("POST", f"{base}/api/mcp", {}, headers)
    challenge = reply_headers.get("WWW-Authenticate", "")
    check("no token is 401", status == 401, status)
    check("401 points at the resource metadata",
          f'resource_metadata="{base}/.well-known/oauth-protected-resource/api/mcp"' in challenge,
          challenge)
    bad = {**headers, "Authorization": "Bearer cad_not-a-real-token"}
    status, _, _ = request("POST", f"{base}/api/mcp", {}, bad)
    check("a made-up token is 401", status == 401, status)

    # Step 4: revoke answers an unknown client without a client_secret field
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    status, _, text = request("POST", f"{base}/revoke", b"token=x&client_id=unknown", form)
    check("revoke with an unknown client is 401, not 400", status == 401, f"{status} {text[:80]}")

    # Step 5: an oversized body is cut off
    big = b'{"email":"' + b"x" * (1024 * 1024 + 1) + b'"}'
    status, _, _ = request("POST", f"{base}/api/auth/login", big, {"Content-Type": "application/json"})
    check("a body over 1 MB is 413", status == 413, status)

    # Step 6: with a real token, the tools answer
    token = os.environ.get("MCP_TOKEN")
    if not token:
        print("SKIP  tool calls (set MCP_TOKEN to run them)")
        return
    auth = {**headers, "Authorization": f"Bearer {token}"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1"}}}
    status, _, text = request("POST", f"{base}/api/mcp", init, auth)
    result = as_json(text).get("result", {})
    check("initialize works", status == 200 and "serverInfo" in result, f"{status} {text[:120]}")
    auth["MCP-Protocol-Version"] = result.get("protocolVersion", "2025-06-18")

    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    status, _, text = request("POST", f"{base}/api/mcp", listing, auth)
    names = {tool["name"] for tool in as_json(text).get("result", {}).get("tools", [])}
    check("tools/list has every tool", TOOLS.issubset(names), f"missing {TOOLS - names}")

    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}}}
    status, _, text = request("POST", f"{base}/api/mcp", call, auth)
    reply = as_json(text).get("result", {})
    check("whoami answers", status == 200 and not reply.get("isError", True), text[:120])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1].rstrip("/"))
    print("all passed" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
