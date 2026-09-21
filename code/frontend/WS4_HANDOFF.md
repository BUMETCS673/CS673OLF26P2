# WS4: decks and cards — integrated with WS3

WS4 now runs inside Duc’s BrowserRouter, AuthProvider and protected routes.
The temporary hash-routing shell and browser-local demo are no longer used by the app.
The demo transport remains only as a test fixture; existing browser demo data is not
uploaded or imported into accounts.

## What changed during integration

- Kept WS3’s `main.jsx` startup, auth, header, routes, and shared client.
- Replaced WS3’s deck placeholders with WS4’s styled pages.
- Page wrappers read route parameters and supply navigation/API props to the views.
- `api/decks.client.js` adapts the nine WS4 operations to WS3’s get/post/patch/del
  helpers, removing the prefix that WS3 adds itself. Cookies and errors go through
  the shared client. No additional fetch wrapper was introduced.
- New-deck creation passes a one-time router flag to open the card composer.
  The flag is consumed so browser Back does not reopen first-time setup.
- “Finish for now” returns to the library during new-deck setup. Ordinary card
  creation uses “Cancel” and stays on the deck.
- The merged dependency files include Duc’s router and WS4’s npm test command.

## Remaining dependency

Von’s WS2 deck/card endpoints are not yet in the develop revision merged here.
The app intentionally uses real endpoints and shows errors if they are unavailable.
Full account-backed persistence requires WS2 to land, followed by browser validation.
Duc’s known expired-session handling gap remains a separate follow-up.

## Run and check

From `code/frontend` with Node 22 or later:

```sh
npm ci
npm test
npm run build
```

Use the repository Docker setup for frontend/backend/PostgreSQL together. Outside
Docker, start Vite with `VITE_API_PROXY_TARGET=http://localhost:5001 npm run dev`.
The backend must be running and its database initialized. Routes are now `/login`,
`/signup`, `/decks`, and `/decks/:id`, without a hash prefix.

The Frontend tests workflow runs npm test on PRs into develop/main and pushes to
those branches. Node tests cover the endpoint contract, demo recovery, and the
actual WS3 client connection (URLs, cookies, serialization, 204s, and API errors).
They do not prove browser session persistence or PostgreSQL behavior.

## Browser acceptance after WS2 lands

1. Sign up, land on the deck library, refresh and remain signed in.
2. Create a deck and immediately add two cards; edit one and delete the other.
3. Finish new-deck setup and return to the library; verify the count.
4. Open an existing deck, add a card, and cancel to stay on that deck.
5. Leave a new deck via the header, then press Back; first-time setup must not replay.
6. Reopen the card composer after an edit; its hint should be fresh and notices
   should have just one live status announcement.
7. Refresh, log out and log in; confirm that the saved deck and cards remain.
8. Check loading, validation, missing-deck errors, and deletion confirmation.

## Files to know

- `src/pages/DeckListPage.jsx`: router wrapper and deck library view.
- `src/pages/DeckDetailPage.jsx`: router wrapper and card management view.
- `src/components/DeckForm.jsx`, `CardForm.jsx`, `CardRow.jsx`: reusable forms/cards.
- `src/api/decks.js`: transport-independent endpoint functions.
- `src/api/decks.client.js`: connection to Duc’s shared client.
- `src/api/decks.demo.js`: standalone demo transport used in tests only.
- `src/ws4.css`: deck/card styles scoped under `.ws4`.

Further commits pushed to feat/ws4-frontend-decks update the existing PR #16.
