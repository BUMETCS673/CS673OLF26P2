# WS4: decks and cards

This branch implements Nurzat's deck list, deck details, reusable forms, and inline
card editing. It currently runs as a clearly labeled **browser-local demo**.
It does not log users in or store data in PostgreSQL. Real authenticated persistence
remains an integration task for WS2, WS3, and WS4 together.

## A quick guide for Nurzat

- A **branch** is a named line of work in Git. `feat/ws4-frontend-decks` uses the
  same project folder as `develop`; it does not create a second folder.
- An **uncommitted change** is an edit saved on disk but not yet recorded as a Git
  snapshot. Branches isolate committed history; commit or stash edits before switching.
- A **commit** records a snapshot locally. A **push** uploads commits to GitHub.
- A **pull request** asks teammates to review and merge the branch into `develop`.
  This implementation does not push or open a PR by itself.

## Files

| File | Purpose |
| --- | --- |
| `src/pages/DeckListPage.jsx` | Load, create, edit, and delete decks; show card counts. |
| `src/pages/DeckDetailPage.jsx` | Load a deck and manage its cards. |
| `src/components/DeckForm.jsx` | Deck name/description fields and validation. |
| `src/components/CardForm.jsx` | Shared create/edit form for card fronts and backs. |
| `src/components/CardRow.jsx` | Display a card, edit it in place, or confirm deletion. |
| `src/api/decks.js` | Nine endpoint functions built around an injected shared client. |
| `src/api/decks.demo.js` | Temporary local-storage data transport. |
| `src/main.jsx` | Temporary demo shell and hash navigation; WS3 will replace it. |
| `src/ws4.css` | Plain CSS scoped under `.ws4`. |
| `tests/decks.test.mjs` | Contract, demo persistence, validation, and failure checks. |

## Run locally

With a current Node.js LTS release and npm installed, from `code/frontend`:

```sh
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://localhost:3000`. `npm ci` installs the exact dependencies in the
existing lockfile. It is only needed when setting up or when that lockfile changes.
No new project packages are required for WS4.

The existing Docker frontend can also serve the demo. The preview itself does not
need the backend. Its URLs use `#/decks` and `#/decks/1` temporarily. Demo data is
saved for this browser and origin under `cadence.ws4.demo.v1`; clearing site data
removes it. There are no accounts or ownership guarantees in the demo.

## Checks

```sh
node --test tests/decks.test.mjs
npm run build
```

Manual browser checklist:

1. Start with no decks; check the empty state and create a deck.
2. Reject a blank name; save a name and optional description.
3. Creating a deck opens its card editor immediately. Add two cards, or choose
   “Finish for now” to return to My decks, even with no cards. Reopen the empty deck:
   it should say “This deck is empty” with one “+ Add card” button at the top right.
   When adding cards from an existing deck, the secondary button is “Cancel”:
   it closes the editor and stays on that deck. Only the automatic editor after
   creating a deck uses “Finish for now” to return to the library.
   Verify “+ New deck”
   appears only once the library has a deck. Rename the deck from the library.
4. Edit one card in place; cancel an edit and verify it was not saved.
5. Cancel a card deletion, then confirm it. Check the card count.
6. Refresh; verify the remaining card and edits survive.
7. Return to all decks; check the count. Cancel deck deletion, then confirm it.
8. Open a nonexistent deck URL; verify the error and way back.
9. Check keyboard navigation, labels, and narrow-window layout.

Node tests exercise data operations, not rendered React interactions. The full
plan's logged-in acceptance flow can only pass after real backend/auth integration.

## Connecting teammates' work

**Duc (WS3):** Keep ownership of `App.jsx`, auth, `client.js`, and dependencies.
Replace the demo shell in `main.jsx` with your app entry point. Import these pages
into the protected `/decks` and `/decks/:id` routes. Keep the API object stable
(create it once outside the component), and pass:

```jsx
<DeckListPage api={decksApi}
  onOpenDeck={(id) => navigate(`/decks/${id}`)}
  onDeckCreated={(id) => navigate(`/decks/${id}`, { state: { startAdding: true } })} />
<DeckDetailPage key={id} api={decksApi} deckId={id}
  startAdding={Boolean(location.state?.startAdding)} onBack={() => navigate('/decks')} />
```

`location` comes from the router's location hook. Ordinary deck navigation should
omit the `startAdding` state; only new-deck creation automatically opens the editor.

Import `ws4.css` and wrap deck pages with `className="ws4"` (or coordinate the
shared layout styles). `id` comes from the router's route parameters. WS3's shared
header should replace the temporary demo header.

`createDecksApi(request)` expects `request(path, { method, body })`. `body` is a
JavaScript object, not serialized JSON. Adapt this call to WS3's chosen client
signature in one place. The shared client handles JSON serialization, headers,
`credentials: 'include'`, JSON responses, empty 204 responses, and errors carrying
`code` and `message`. Coordinate unauthorized-session handling with AuthContext.
No WS4 component calls `fetch`, and no replacement shared client is introduced.

**Von (WS2):** Supply the nine endpoints in the existing iteration contract.
Deck responses include `card_count`; card responses include `deck_id`. Lists are
arrays. Missing or unowned resources return 404, invalid fields 422, and successful
deletions 204. WS4 does not modify backend files or the contract.

Once connected, remove the demo transport/imports and demo banner, then repeat the
acceptance flow against real login and PostgreSQL, including logout/login and refresh.
