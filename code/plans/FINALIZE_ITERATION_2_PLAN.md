# Cadence — Finalize Iteration 2: Study Mode, End to End

**Status:** Draft 2, for team review. Nothing here is final until we agree on it in the channel.
**Dates:** _TBD_ → Iteration 2 demo _TBD_
**Team:** Miles, Duc, Nurzat, Von
**Builds on:** [ITERATION_1_PLAN.md](ITERATION_1_PLAN.md) and [LAB_3_PLAN.md](LAB_3_PLAN.md)

## What we're building

Lab 3 built the parts of study mode: Anki's scheduler, the due-cards and review endpoints, and the
session reducer. Each one is tested and on `develop`, and none of them shows up in the app. Open
`localhost:3000` today and you get the Iteration 1 demo: decks and cards, and no way to study
them.

This plan connects the parts. When it's done, a learner can:

1. See on the deck list how many cards are waiting in each deck.
2. Open a deck, see where each card stands ("New", "Learning · in 6m", "Review · in 25d"), and
   press **Study now**.
3. Study one card at a time: read the front, reveal the back, and rate it with four buttons that
   each show when the card would come back ("Again 10m · Hard 12d · Good 1mo · Easy 1.5mo").
4. Finish with a summary, go back to the deck, and see every card rescheduled where Anki would
   put it.
5. Refresh or sign out in the middle of a session and lose nothing except that session's counts.

The app also gets one look. The sign-in pages and the deck pages were styled separately in
Iteration 1 and don't match. Step 0c gives every page the same fonts, a blue and gold palette, and
the same buttons, forms, and panels, from a short [style guide](#style-guide).

The demo also gets data that shows all of this. `flask seed` adds a second deck with cards in
every state, so nobody has to wait a day for a review card to come due.

There are no new tables, migrations, or packages. Nearly all of this is wiring and styling.

## Contents

- [Who's doing what](#whos-doing-what)
- [Where the code is today](#where-the-code-is-today)
- [Architecture](#architecture)
- [API contract changes](#api-contract-changes)
- [Frontend contracts](#frontend-contracts)
- [Style guide](#style-guide)
- [Chunks in detail](#chunks-in-detail)
- [Schedule](#schedule)
- [Decisions we made](#decisions-we-made)
- [Out of scope](#out-of-scope)
- [Working with an AI agent](#working-with-an-ai-agent)

---

## Who's doing what

| # | Chunk | Side | Owner | Depends on | Size | Demo needs it? |
| --- | --- | --- | --- | --- | --- | --- |
| **0a** | **CI green on `develop`**: stop the GitHub Actions cache from skipping the frontend image's security upgrade | DevOps | Miles | nothing | XS | 🔴 blocks every merge |
| **0b** | **Frontend foundation**: the study API client, `formatInterval()`, the route, a placeholder page, and stub components | frontend | Miles | nothing | S | 🔴 blocks F1–F3 |
| **0c** | **Style foundation**: the style guide's tokens and shared classes, and the existing pages restyled to match | frontend | Miles | nothing | M | 🔴 blocks every frontend chunk's CSS |
| **B1** | **Demo data**: a seeded deck with cards in every state, plus `--reset` | backend | Miles | nothing | S | 🔴 |
| **B2** | **Due counts**: `due_counts` on every `Deck` | backend | Nurzat | nothing | M | 🟡 |
| **B3** | **Interval previews**: `intervals` on study cards | backend | Von | nothing | S | 🟡 |
| **F1** | **Study page**: `StudyView`, the session, and the review calls | frontend | Duc | 0b; 0c for styles | M | 🔴 |
| **F2** | **Card and rating buttons** | frontend | Miles | 0b; 0c for styles | S | 🔴 |
| **F3** | **Session summary** | frontend | Duc | 0b; 0c for styles | S | 🔴 |
| **F4** | **Deck pages**: a Study button, due counts, and a schedule badge on each card | frontend | Nurzat | 0b and 0c | M | 🔴 |
| **R** | **Walkthrough, docs, and release** | QA / docs | Miles | everything | S | 🔴 |

🔴 means the demo doesn't work without it. 🟡 means the demo works without it but is noticeably
weaker. The one 🟢 (optional) item is B1's `flask time-travel` command, marked where it appears.

Steps 0a, 0b, and 0c play the role Step 0 played in Lab 3: they land first, and the chunks after
them build on them. 0a is already up for review as #44. 0b unblocks the study page's logic and
tests; 0c unblocks everyone's styling. Neither waits on the other.

The backend chunks don't depend on each other or on the frontend. The frontend chunks can merge
before the backend ones, because the frontend renders without the new fields until they arrive
([rule 10](#rules-that-keep-the-code-consistent)). Merge order only matters where the table says
so.

---

## Where the code is today

### What Lab 3 left on `develop`

| Lab 3 piece | Status | What the app does with it today |
| --- | --- | --- |
| Step 0a: scheduling columns, `Card.schedule` | merged, #36 | `Card` JSON carries `state` and `due_at`, but nothing displays them |
| Step 0b: Vitest and React Testing Library, `constants.js` | merged, #37 | component tests work; there's one so far (`CardRow`) |
| Story 1: `answer_card()` | merged, #39 | the review endpoint calls it |
| Story 2: `GET /api/decks/:id/due` | merged, #41 | nothing calls it |
| Story 3: `sessionReducer` in `session.js` | merged, #40 | nothing imports it |
| Story 4: `checkTypedAnswer()` in `typedAnswer.js` | not on `develop` | not part of Iteration 2 (decision [P6](#decisions-we-made)) |
| Story 5: `POST /api/cards/:id/review` | merged, #42 | nothing calls it |

### Why the demo still looks like Iteration 1

There are six gaps, all on the seams between the parts:

1. **No study page and no route.** `App.jsx` has `/decks` and `/decks/:id` and nothing else.
2. **No frontend client for the new endpoints.** `createDecksApi` has the nine Iteration 1 calls.
3. **No way in.** Nothing on the deck pages starts a session or says what's due.
4. **No schedule on screen.** `CardRow` ignores `state` and `due_at`.
5. **The seed data is all new cards.** A fresh database has nothing in learning or review, so
   the scheduler's most interesting behavior stays hidden unless we wait a day.
6. **Two styles.** The sign-in pages and the header use `styles.css` (WS3): the system font, a
   cool gray palette, and a blue that a bare `button` rule applies to every button in the app.
   The deck pages use `ws4.css` (WS4), scoped under `.ws4`: a second font stack, a green palette,
   and a `body:has(.ws4)` rule that repaints the page background. Even the header doesn't match
   the deck page under it.

### Two things to know before starting

**CI on `develop` is red.** The runs after both of the last two merges (#42 and #41) failed the
Docker job and nothing else: Trivy found four HIGH OpenSSL CVEs (`libcrypto3` and `libssl3`,
fixed in `3.3.7-r2`) in the frontend's `prod` image. The Dockerfile already runs
`apk upgrade --no-cache` for exactly this reason, but the build log shows
`[prod 2/4] RUN apk upgrade --no-cache` as `CACHED`. The GitHub Actions layer cache served an
older layer, so the upgrade never ran against the patched packages. Every test job passed. Step
0a fixes it, and is up for review as #44.

**Pull `develop` before you demo.** If you ran the app from a Lab 3 feature branch, you were
missing at least one of the endpoints.

### What this plan builds on

| File | What's there |
| --- | --- |
| `frontend/src/study/session.js` | `initSession({ due, now })` and `sessionReducer` with `reveal`, `answered`, and `skipped`. The state holds `current`, `revealed`, `finished`, `counts`, `nextLearningDue`, `learning`, and `main` |
| `frontend/src/study/constants.js` | `RATINGS` and `LEARN_AHEAD_MS` |
| `frontend/src/api/decks.js`, `decks.client.js`, `useDecksApi.js` | the pattern to copy: an endpoint module that doesn't know about `fetch`, an adapter onto `client.js`, and a hook that signs you out on a 401 |
| `frontend/src/pages/DeckDetailPage.jsx` | the page pattern to copy: a thin wrapper that reads the router, and a `DeckDetailView({ api, ... })` that a test can render with a fake `api` |
| `frontend/src/styles.css`, `ws4.css` | the two stylesheets 0c merges into one design system |
| `backend/app/api/decks.py` | `get_due_cards()`: three queries sharing one `utcnow()` |
| `backend/app/api/cards.py` | `review_card()` and `_is_due()`, which answers 409 for a card that isn't due |
| `backend/app/scheduler.py` | `answer_card()` and the session limits |
| `backend/app/seed.py` | the demo user and one deck of four new cards. Does nothing if the user already exists |
| `backend/tests/test_foundation.py` | `test_card_count_does_not_query_per_deck`, the query-counting pattern B2 reuses |

The CI rules from Lab 3 all still hold: backend coverage at 90% or above, the backend tests also
run on Postgres, migrations have to match the models, and the frontend has to pass `eslint`,
`npm test`, and `npm run build`.

---

## Architecture

### New and changed files

```
.github/workflows/
  ci.yml, cd.yml                         # 0a: no-cache-filters on the frontend image build
code/
  plans/
    FINALIZE_ITERATION_2_PLAN.md         # this file
  Readme.md                              # R: demo data and the walkthrough
  backend/
    app/
      scheduler.py                       # B3: + preview_intervals()
      seed.py                            # B1: + the "Travel Spanish" deck, --reset
                                         #     (optional: flask time-travel)
      models/card.py                     # B3: + Card.to_study_dict(now)
      api/decks.py                       # B2: due_counts on every Deck, _due_conditions()
                                         # B3: /due returns study cards
      api/cards.py                       # B3: the review response is a study card
    tests/
      test_seed.py                       # B1
      test_deck_due_counts.py            # B2
      test_interval_preview.py           # B3
  frontend/
    index.html                           # 0c: the two fonts
    src/
      App.jsx                            # 0b: + /decks/:id/study
      styles.css                         # 0c: the design system: tokens and shared classes
      ws4.css                            # 0c: deck-page layout only, on the tokens   F4
      study.css                          # 0b: one section per chunk; F1-F3 each fill theirs
      api/
        request.js                       # 0b: transport and 401 handling, moved out of decks.client.js
        decks.client.js                  # 0b: built on request.js, behavior unchanged
        study.js                         # 0b: createStudyApi(request)
        study.client.js                  # 0b: createAuthenticatedStudyApi(onUnauthorized)
        useStudyApi.js                   # 0b
      study/
        formatInterval.js                # 0b
        describeSchedule.js              # F4
      pages/
        LoginPage.jsx, SignupPage.jsx    # 0c: shared classes and the wordmark
        StudyPage.jsx                    # 0b: placeholder   F1: the page
        DeckDetailPage.jsx               # F4
        DeckListPage.jsx                 # F4
      components/
        Header.jsx                       # 0c: the navy header
        CardRow.jsx                      # F4: schedule badge
        study/
          StudyCard.jsx                  # 0b: stub   F2
          RatingButtons.jsx              # 0b: stub   F2
          SessionSummary.jsx             # 0b: stub   F3
    tests/
      study-api.test.mjs                 # 0b
      study-client.test.mjs              # 0b
      formatInterval.test.mjs            # 0b
      StudyPage.test.jsx                 # F1
      StudyCard.test.jsx                 # F2
      RatingButtons.test.jsx             # F2
      SessionSummary.test.jsx            # F3
      describeSchedule.test.mjs          # F4
      CardRow.test.jsx                   # F4: + badge tests
      DeckDetailView.test.jsx            # F4
      DeckListView.test.jsx              # F4
```

Each file belongs to one chunk. If you need a file someone else owns, message them instead of
editing it.

### Shared files

| File | Why it's shared | Rule |
| --- | --- | --- |
| `frontend/src/App.jsx` | the one new route | Step 0b only |
| `frontend/src/api/decks.client.js` | 0b moves its transport into `request.js` | Step 0b only. `decks-client.test.mjs` has to pass without edits, which proves nothing changed |
| `frontend/src/study/session.js`, `constants.js` | F1 is built on them | Nobody. Frozen (decision [P1](#decisions-we-made)) |
| `frontend/src/styles.css` | every page's look comes from it | Step 0c only. Need a new token or shared class? Ask in the channel, and 0c's owner adds it |
| `frontend/src/ws4.css` | 0c rewrites it, then F4 restyles the deck pages | 0c first. F4 edits it only after 0c has merged |
| `frontend/src/pages/LoginPage.jsx`, `SignupPage.jsx`, `components/Header.jsx` | WS3's files; 0c changes their class names and markup | Step 0c only, and no behavior changes |
| `frontend/src/pages/StudyPage.jsx` | 0b writes a placeholder, F1 builds the page | F1 owns it once 0b has merged |
| `frontend/src/components/study/*.jsx` | F1 renders them, F2 and F3 build them | 0b writes stubs with [the agreed props](#the-study-components-0b-stubs-f2-and-f3-build-them). Each owner replaces their stubs' insides and keeps the props |
| `frontend/src/study.css` | one stylesheet for the study page | 0b creates a commented section per chunk. Edit only yours, and only after 0c has merged |
| `backend/app/api/decks.py` | B2 changes the deck routes, B3 changes what `/due` returns | B2 owns the deck routes and `_due_conditions()`. B3 changes only the `jsonify(...)` at the end of `get_due_cards()`. Whoever merges second rebases; the overlap is a few lines |
| `backend/app/scheduler.py` | B3 adds a function | B3 adds `preview_intervals()`. Everything already in the file stays frozen |
| `backend/app/models/card.py` | B3 adds a method | B3 only. `to_dict()` doesn't change |

Nobody touches these: `session.js`, `constants.js`, `Card.to_dict()`, `Deck.to_dict()`,
`errors.py`, `api/__init__.py`, `package.json`, `package-lock.json`, `requirements.txt`, and the
migrations.

### How the pieces fit

```
DeckListPage (F4) ── GET /api/decks ─────────▶ every Deck + due_counts (B2)
  │                  "Travel Spanish · 6 due · 3 new"   [Study]
  ▼
DeckDetailPage (F4) ─ GET /api/decks/2 ───────▶ Deck + due_counts (B2)
  │                   GET /api/decks/2/cards ─▶ Cards, with state and due_at (Lab 3)
  │                   each CardRow: "Review · in 25d"   [Study now · 9]
  ▼  navigate to /decks/2/study
StudyPage (0b route, F1 page)
  │ 1. GET /api/decks/2       deck name
  │    GET /api/decks/2/due   { learning, review, new }, each card + intervals (B3)
  │ 2. useReducer(sessionReducer, { due, now }, initSession)        (Lab 3 Story 3, unchanged)
  │ 3. StudyCard (F2) shows the front; [Show answer] or Space ──▶ dispatch reveal
  │ 4. RatingButtons (F2): "Good 1mo", from card.intervals.good via formatInterval (0b)
  │      click or 1-4 ──▶ POST /api/cards/9/review {rating}
  │        200      ──▶ dispatch answered { rating, card: <the response>, now }
  │        409, 404 ──▶ dispatch skipped { now }
  │        401      ──▶ expireSession(), and ProtectedRoute sends you to /login
  │        other    ──▶ keep the card, show the error, let the learner try again
  │ 5. state.finished ──▶ SessionSummary (F3) ──▶ [Study more] refetches  [Back to deck]

Every page above, and the sign-in pages, take their look from styles.css (0c).
```

### Rules that keep the code consistent

Rules 1–9 from the Iteration 1 and Lab 3 plans still apply. Five more:

10. **Every new response field is optional on the frontend.** `deck.due_counts` (B2) and
    `card.intervals` (B3) may be missing. Render without them: no count, no interval under the
    button. That's what lets the frontend and backend chunks merge in any order.
11. **One review request per card shown.** Send `POST /review` from a click or key handler, never
    from an effect, and guard it with a ref as well as `disabled`. React's StrictMode runs every
    effect twice in development, and the server won't catch every duplicate. Its 409
    ([L7](LAB_3_PLAN.md#decisions-we-made)) stops a second answer on a review card, but not on a
    learning card. A new card rated Good is due again in 10 minutes, which is inside the
    20-minute learn-ahead window, so a second Good is accepted and graduates the card to a 1-day
    review. The page is the only thing that can stop that.
12. **Views take `api` as a prop.** Do it the way `DeckListView` and `DeckDetailView` do: a thin
    page wrapper reads the router and the hooks, and passes `api` and callbacks to the view. Then
    component tests pass a fake `api` object instead of mocking `fetch`. Only 0b's adapter tests
    mock `fetch`.
13. **No new packages and no schema changes.** That means component tests use React Testing
    Library's `fireEvent`, since `user-event` isn't installed. If you find yourself writing a
    migration, stop and ask in the channel: that's the review-history table, which is
    [out of scope](#out-of-scope).
14. **Every page's look comes from `styles.css`.** Use the [style guide](#style-guide)'s tokens
    and shared classes. No hex colors, font names, or one-off buttons anywhere else: a page
    stylesheet like `study.css` or `ws4.css` holds layout, and reaches for `var(--color-…)` when
    it needs a color.

---

## API contract changes

Same rule as both earlier plans: agree on this before writing code. If something here turns out
to be wrong, say so in the channel and we change it together. Everything in the Iteration 1 and
Lab 3 contracts stays as it is. Both changes add fields and remove nothing.

### `Deck` gains `due_counts` (B2)

```jsonc
{
  "id": 2,
  "name": "Travel Spanish",
  "description": "English → Spanish, with cards at every stage",
  "card_count": 11,
  "due_counts": { "learning": 3, "review": 3, "new": 3 },
  "created_at": "2026-10-01T14:00:00Z",
  "updated_at": "2026-10-01T14:00:00Z"
}
```

- It's on every response that returns a `Deck`: `GET /api/decks`, `GET /api/decks/:id`,
  `POST /api/decks`, and `PATCH /api/decks/:id`.
- Each number is exactly the length of the matching list that `GET /api/decks/:id/due` would
  return at the same moment. Same conditions, same caps (200 reviews, 20 new), same 20-minute
  learn-ahead window. A deck with no cards gets three zeros.
- `Deck.to_dict()` doesn't change. The counts depend on the time, and models never read the clock
  (rule 8), so the route adds them.

### Study cards gain `intervals` (B3)

```jsonc
{
  "id": 9,
  "deck_id": 2,
  "front": "the suitcase",
  "back": "la maleta",
  "state": "learning",
  "due_at": "2026-10-01T13:58:00Z",
  "created_at": "2026-10-01T14:00:00Z",
  "updated_at": "2026-10-01T14:00:00Z",
  "intervals": { "again": 60, "hard": 600, "good": 86400, "easy": 345600 }
}
```

- `intervals[rating]` is how many whole seconds from now the card would be due if the learner
  answered it with `rating` right now: `answer_card(card.schedule, rating, now).due_at - now`.
- It's on every card in all three lists of `GET /api/decks/:id/due`, and on the
  `POST /api/cards/:id/review` response, where it describes the card's *next* answer. It's
  nowhere else: `GET /api/decks/:id/cards` and `PATCH /api/cards/:id` return `Card` exactly as
  before.
- The frontend formats these numbers and never works them out itself (rule 6).

Reference values, computed with the scheduler on `develop`:

| Card | `again` | `hard` | `good` | `easy` |
| --- | --- | --- | --- | --- |
| new, or learning on step 0 | 60 | 330 | 600 | 345600 (4d) |
| learning on step 1 | 60 | 600 | 86400 (1d) | 345600 (4d) |
| relearning, `interval_days` 1 | 600 | 900 | 86400 (1d) | 172800 (2d) |
| review, I = 10, 250%, on time | 600 | 1036800 (12d) | 2160000 (25d) | 2851200 (33d) |
| review, I = 10, 250%, 4 days overdue | 600 | 1036800 (12d) | 2592000 (30d) | 3974400 (46d) |

Every number here also appears in Story 1's tables in the Lab 3 plan, so the preview tests double
as a check that previews call the real scheduler.

### How the study page handles each review response

The endpoints are unchanged, but this is the first time the frontend calls them, so here's what
it does with each answer from `POST /api/cards/:id/review`:

| Status | `code` | The study page |
| --- | --- | --- |
| 200 | | dispatches `answered` with the card from the response |
| 401 | `unauthorized` | nothing extra: the authenticated adapter calls `expireSession()`, and `ProtectedRoute` sends the learner to `/login` |
| 404 | `not_found` | dispatches `skipped`. The card was deleted, most likely in another tab |
| 409 | `conflict` | dispatches `skipped`. The card isn't due yet, usually because the browser's clock and the server's disagree |
| 422 | `validation_error` | shows the message. The buttons can only send the four ratings, so this means a bug |
| 500, or `network_error` | | keeps the card showing and revealed, shows the message, and leaves the buttons enabled so the learner can try again |

---

## Frontend contracts

These are the seams between the frontend chunks. Step 0b writes each signature into the code
before anyone builds on it.

### `createStudyApi(request)` (0b)

Built the same way as `createDecksApi`, so it can be tested without `fetch`:

```js
export function createStudyApi(request) {
  const id = (value) => encodeURIComponent(value);
  return {
    getDueCards: (deckId) => request(`/api/decks/${id(deckId)}/due`),
    reviewCard: (cardId, rating) =>
      request(`/api/cards/${id(cardId)}/review`, { method: 'POST', body: { rating } }),
  };
}
```

`useStudyApi()` returns this connected to `client.js`, calling `expireSession()` on any 401,
exactly like `useDecksApi()`. Errors arrive as `client.js`'s `ApiError`, so callers switch on
`err.code`.

### `formatInterval(seconds)` (0b)

Pure, in `src/study/formatInterval.js`. It turns a number of seconds into the short label Anki
puts on its buttons. Round at each unit, and move up a unit when the rounded value reaches the
next one:

| Seconds | Label | Why |
| --- | --- | --- |
| 0, 59 | `<1m` | under a minute |
| 60 | `1m` | |
| 330 | `6m` | 5.5 minutes rounds up |
| 600, 900 | `10m`, `15m` | |
| 3570 | `1h` | 59.5 minutes rounds to 60, which is an hour |
| 3600 | `1h` | |
| 86400, 345600 | `1d`, `4d` | |
| 25 days | `25d` | |
| 30 days | `1mo` | a month is 30 days |
| 45 days, 238 days | `1.5mo`, `7.9mo` | one decimal place, dropped when it's `.0` |
| 365 days | `1y` | a year is 365 days |
| 476 days, 36500 days | `1.3y`, `100y` | |

F2, F3, and F4 all call it, which is why it's in Step 0b rather than in one of them.

### `StudyView` (F1)

```
<StudyView api deckId onExit now />

  api     { getDeck(deckId), getDueCards(deckId), reviewCard(cardId, rating) }
  deckId  string, from the route
  onExit  () => void, back to the deck page
  now     () => number, in milliseconds. Defaults to Date.now; tests pass a fixed clock
```

The `StudyPage` wrapper builds `api` from `useDecksApi().getDeck` and `useStudyApi()`, wrapped in
`useMemo` so it doesn't change on every render.

### The study components (0b stubs, F2 and F3 build them)

Step 0b writes each of these as a stub that already behaves the way the last column describes,
just without styling. F1's tests rely on that column, so they keep passing when F2 and F3 replace
the stubs.

| Component | Props | Tests can rely on |
| --- | --- | --- |
| `StudyCard` (F2) | `card`: a `Card` (`front`, `back`, `state`). `revealed`: boolean | The front is always visible. The back isn't in the DOM at all until `revealed` is true |
| `RatingButtons` (F2) | `intervals`: `{ again, hard, good, easy }` in seconds, or undefined. `disabled`: boolean. `onRate(rating)` | Four `<button>`s in `RATINGS` order. Each accessible name starts with `Again`, `Hard`, `Good`, or `Easy`. A click calls `onRate` once with the lowercase rating. `disabled` disables all four |
| `SessionSummary` (F3) | `counts`: `{ again, hard, good, easy }`. `nextLearningDue`: ISO string or null. `now`: milliseconds. `onStudyMore()`. `onExit()` | Heading `Session complete` when any count is above 0, otherwise `Nothing to study right now`. A `Back to deck` button calls `onExit`. When `nextLearningDue` is set, a `Study more` button calls `onStudyMore` |

### The session itself (Lab 3 Story 3, unchanged)

F1 uses the reducer exactly as it is (decision [P1](#decisions-we-made)):

- Start: `useReducer(sessionReducer, { due, now: now() }, initSession)`. `initSession` takes
  exactly that object, so it works as `useReducer`'s third argument with no wrapper.
- Reveal: `dispatch({ type: 'reveal' })`.
- After a 200: `dispatch({ type: 'answered', rating, card: response, now: now() })`.
- After a 404 or 409: `dispatch({ type: 'skipped', now: now() })`.
- Cards left: `state.main.length + state.learning.length + (state.current ? 1 : 0)`.
- Finished: `state.finished`, with `state.counts` and `state.nextLearningDue` for the summary.

### `describeSchedule(card, now)` and `describeDueCounts(dueCounts)` (F4)

Pure, in `src/study/describeSchedule.js`, and built on `formatInterval()`.

| `describeSchedule(card, now)` | Returns |
| --- | --- |
| `state: 'new'` | `New` |
| learning, due 2 minutes ago | `Learning · due now` |
| learning, due in 330 seconds | `Learning · in 6m` |
| relearning, due in 10 minutes | `Relearning · in 10m` |
| review, due 3 days ago | `Review · due now` |
| review, due in 25 days | `Review · in 25d` |

| `describeDueCounts(dueCounts)` | Returns |
| --- | --- |
| `undefined` (B2 not merged yet) | `null`, and the caller renders nothing |
| `{ learning: 3, review: 3, new: 3 }` | `6 due · 3 new` |
| `{ learning: 0, review: 0, new: 4 }` | `4 new` |
| `{ learning: 1, review: 2, new: 0 }` | `3 due` |
| all zero | `All caught up` |

"Due" is learning plus review. New cards are counted separately, because the learner hasn't seen
them yet.

---

## Style guide

Step 0c builds this into `styles.css`, and every frontend chunk after it uses it (rule 14). It's
deliberately short: enough that pages written by four people look like one app, and no more.

### The feel

Clean and calm. White panels on a cool off-white page, navy text, blue for anything you can
click, and gold as a sparing accent. Generous space, one corner radius, one soft shadow.

### Type

| Use | Font | Weight | Size |
| --- | --- | --- | --- |
| Headings and the wordmark | Plus Jakarta Sans | 700 for `h1` and the wordmark, 600 for `h2` and `h3` | `h1` 32px (28px under 640px wide), `h2` 20px, `h3` 16px |
| Everything else | Inter | 400 for text, 600 for labels and buttons | 15px with a 1.55 line height; small text 13px |
| Eyebrows, the small capitals above a heading | Inter | 600 | 11px, uppercase, `0.12em` letter-spacing |
| Counts and intervals | Inter, with `font-variant-numeric: tabular-nums` | | so numbers don't shift as they change |

Both fonts load from Google Fonts with a `<link>` in `index.html`, not an npm package (rule 13):

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Plus+Jakarta+Sans:wght@600;700&display=swap" />
```

If they don't load, every stack falls back to the system font.

### Tokens

Step 0c puts exactly these on `:root` in `styles.css`. Nothing outside this block names a color or
a font.

```css
:root {
  --font-heading: "Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-body: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;

  --color-text: #16213a;          /* body text and headings */
  --color-muted: #5a6478;         /* secondary text, hints, captions */
  --color-bg: #f6f8fb;            /* the page */
  --color-surface: #ffffff;       /* panels, cards, inputs */
  --color-border: #dce2ec;        /* panel and input borders, dividers */

  --color-navy: #0e2341;          /* the header; the Easy accent */
  --color-primary: #1e4e9c;       /* primary buttons, links, text buttons; the Good accent */
  --color-primary-hover: #173e7d;
  --color-primary-soft: #e8effa;  /* tinted backgrounds: card-state badges */

  --color-gold: #c9a227;          /* on navy only: the wordmark */
  --color-gold-strong: #a8800f;   /* focus ring, accent bars; the Hard accent */
  --color-gold-soft: #fbf3dc;     /* due-count badge background */
  --color-gold-text: #7a5a00;     /* gold text on a light background */

  --color-danger: #b42318;        /* errors, delete; the Again accent */
  --color-danger-soft: #fef0ee;   /* error and delete-confirmation backgrounds */

  --radius: 10px;                 /* panels */
  --radius-control: 8px;          /* buttons and inputs */
  --shadow: 0 1px 2px rgb(14 35 65 / 6%), 0 4px 12px rgb(14 35 65 / 4%);

  --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px; --space-8: 64px;
}
```

Every text color passes WCAG AA against the background it's used on (4.5:1 or better), and the
focus ring and accent bars pass the 3:1 that non-text marks need. Bright gold on white is only
2.4:1, which is why `--color-gold` appears on navy and nowhere else.

**Gold is an accent.** The wordmark, the focus ring, due-count badges, and thin accent bars. Never
body text on white, never a large fill, never a primary button.

### Shared pieces

Step 0c makes these global, so the sign-in pages, the deck pages, and the study page all use the
same ones. Most of the class names are WS4's, since the deck pages already use them.

| Piece | Classes | Looks like |
| --- | --- | --- |
| Header | `.app-header` | a 64px navy bar. "Cadence" in Plus Jakarta Sans, white, with a gold dot. The signed-in name in muted white. **Sign out** as a ghost button: white text, a translucent white border |
| Page | `.page`, `.page-heading`, `.eyebrow`, `.subtitle` | content at most 1120px wide, 24px gutters (16px under 640px), 48px below the header. The heading on the left, the page's main action on the right |
| Panel | the look shared by `.auth-card`, `.deck-tile`, `.card-row`, `.form-panel`, `.state-panel`, and the study card | `--color-surface`, a 1px `--color-border` border, `--radius`, `--shadow` |
| Buttons | `.button` with `.primary`, `.secondary`, or `.destructive`; `.text-button` | 40px tall, `--radius-control`, Inter 600 at 14px. Primary is a blue fill with white text; secondary is white with a border and navy text; destructive is a red fill. A text button is blue text with no box. Disabled is 55% opacity |
| Fields | `label`, `input`, `textarea`, `.field-hint`, `.field-error`, `.form-actions` | labels at 13px 600; white inputs with a border that turns blue on focus; errors in `--color-danger` under the field |
| Alerts | `.error-message`, with `role="alert"` | `--color-danger-soft` background and `--color-danger` text |
| Badges | `.badge`, `.badge-gold`, `.badge-blue` | a pill at 12px 600. Gold for due counts, blue for card states, plain for anything else |
| Focus | every interactive element | `outline: 3px solid var(--color-gold-strong); outline-offset: 2px` |
| Empty, loading, and error states | `.state-panel`, `.empty-state` | the same on every page |
| Screen-reader text | `.sr-only` | as WS4 wrote it |

**Rating buttons (F2)** are `.button.secondary` with a 3px top accent bar: Again
`--color-danger`, Hard `--color-gold-strong`, Good `--color-primary`, Easy `--color-navy`.

**Not this iteration:** dark mode, icons beyond the text symbols already in use, animation beyond
hover and focus transitions, and any CSS framework or component library.

---

## Chunks in detail

Test-first is still how we work, but there are no red/green screenshots this time. Name each test
after its acceptance row, as in Lab 3, so the list of tests reads like the table.

### Step 0a — CI green on `develop` 🔴 blocks every merge

**Owner:** Miles · **Roughly:** 1 hour · **After:** nothing · **Status:** up for review as #44
**Files:** `.github/workflows/ci.yml`, `.github/workflows/cd.yml`

- In the **frontend** image build step of both workflows, add `no-cache-filters: prod` to
  `docker/build-push-action`. The `prod` stage is `apk upgrade` and two `COPY`s, so rebuilding it
  every time costs seconds. In exchange, the upgrade always runs against the current Alpine
  packages, and this failure can't come back the next time a CVE is published.
- Leave the backend image alone. Its `apt-get upgrade` is in the `base` stage along with
  `pip install`, so the same fix would reinstall every dependency on every build. Its scan is
  passing; apply the fix there only if it fails the same way.

**Done when:** the CI run on `develop` after 0a merges is green, "CI passed" included. Post in the
channel.

---

### Step 0b — Frontend foundation 🔴 blocks F1–F3

**Owner:** Miles · **Roughly:** 3–4 hours · **After:** nothing
**Files:** `src/api/request.js`, `decks.client.js`, `study.js`, `study.client.js`,
`useStudyApi.js`, `src/study/formatInterval.js`, `App.jsx`, `src/pages/StudyPage.jsx`, the three
stubs in `src/components/study/`, `src/study.css`, `tests/study-api.test.mjs`,
`tests/study-client.test.mjs`, `tests/formatInterval.test.mjs`

**The API client**

- `src/api/request.js`: move the two pieces of `decks.client.js` that aren't about decks into
  here. `requestDeck` becomes `requestApi(path, { method, body })`, and the 401 handling inside
  `createAuthenticatedDecksApi` becomes `withSessionExpiry(request, onUnauthorized)`.
  `decks.client.js` keeps both of its exports, now built from these. `decks-client.test.mjs`
  passes without edits, which is the proof nothing changed.
- `src/api/study.js`: [`createStudyApi(request)`](#createstudyapirequest-0b), exactly as written.
- `src/api/study.client.js`: `createAuthenticatedStudyApi(onUnauthorized)`, which is
  `createStudyApi(withSessionExpiry(requestApi, onUnauthorized))`.
- `src/api/useStudyApi.js`: the same as `useDecksApi.js`, using that function.
- `tests/study-api.test.mjs`: both calls use the agreed path, method, and body. Copy the first
  test in `decks.test.mjs`.
- `tests/study-client.test.mjs`, through the real `client.js` with `fetch` mocked the way
  `decks-client.test.mjs` does it: `getDueCards(3)` is a `GET` to `/api/decks/3/due` with
  cookies; `reviewCard(9, 'good')` is a `POST` to `/api/cards/9/review` with the body
  `{"rating":"good"}`; a 409 rejects with `{ status: 409, code: 'conflict' }`; and a 401 calls
  `onUnauthorized` and still rejects.

**The pure helper**

- `src/study/formatInterval.js` and `tests/formatInterval.test.mjs`: one test per row of
  [the table](#formatintervalseconds-0b). No React imports (rule 9).

**The scaffold**

- `App.jsx`: `/decks/:id/study`, inside `ProtectedRoute`, pointing at `StudyPage`.
- `src/pages/StudyPage.jsx`: the wrapper described under [`StudyView`](#studyview-f1), with a
  placeholder `StudyView` that renders the deck's name, "Study mode is on its way", and a back
  button. F4's button then has somewhere to go from the first day.
- `src/components/study/`: the three stubs. Each one has a JSDoc block with its props from
  [the table](#the-study-components-0b-stubs-f2-and-f3-build-them), and plain markup that already
  does what the table's last column says. The `RatingButtons` stub, for instance, is four
  unstyled buttons that call `onRate`.
- `src/study.css`: a `.study` root and one commented section per chunk (`/* F1: page */`,
  `/* F2: card and buttons */`, `/* F3: summary */`), with no rules in them yet. `StudyPage.jsx`
  imports it.

**Done when:** `npm test`, `eslint`, and `npm run build` pass; signed in, `/decks/1/study` shows
the placeholder; and signed out, it sends you to `/login`. Post in the channel.

---

### Step 0c — Style foundation 🔴 blocks every frontend chunk's CSS

**Owner:** Miles · **Roughly:** 5–6 hours · **After:** nothing
**Files:** `index.html`, `src/styles.css`, `src/ws4.css`, `src/pages/LoginPage.jsx`,
`src/pages/SignupPage.jsx`, `src/components/Header.jsx`

> *As a learner, I want every page of Cadence to look like part of one app, so that it feels
> trustworthy and I can find my way around it.*

- `index.html`: the font `<link>`s from [the style guide](#type).
- `src/styles.css`: becomes the design system. The [tokens](#tokens) on `:root`; base styles for
  the body, headings, links, and the focus ring; and every [shared piece](#shared-pieces), global.
  Remove the bare `button` rule, which today paints every button in the app blue. Buttons get
  their look from `.button` and `.text-button` only.
- `src/ws4.css`: keep only what belongs to the deck pages (the deck grid, tiles, card rows, the
  card composer), still scoped under `.ws4`, with every color and font rewritten as a token.
  Remove its own palette (`--ink`, `--green`, and the rest), its font stack, the `body:has(.ws4)`
  background override, the rules that are now global, and the leftovers from WS4's standalone
  demo shell (`.app-header`, `nav`, `.demo-banner`, `.workspace-label`, and `.app-footer` under
  `.ws4`). Where a deck page has its own name for a shared piece, such as `.ws4-page` for
  `.page`, style both from one rule instead of renaming the JSX F4 is about to edit.
- `LoginPage.jsx` and `SignupPage.jsx`: the shared classes (`button primary` on the submit button,
  `.error-message` in place of `.form-error`), and the wordmark above the form. No behavior
  changes.
- `Header.jsx`: the wordmark and the ghost **Sign out** button. No behavior changes.
- Then check every existing screen against the guide: sign in, sign up with field errors, the
  empty and the full deck list, creating a deck, a deck with cards, editing a card, a delete
  confirmation, a load error, and the study placeholder if 0b has merged.

**Done when:** `npm test`, `eslint`, and `npm run build` pass; this finds nothing outside the
token block at the top of `styles.css`:

```bash
grep -rnE '#[0-9a-fA-F]{3,8}\b|"Inter"|Jakarta|system-ui' src --include='*.css'
```

and the PR has before-and-after screenshots of the sign-in page, the deck list, and a deck. Post
in the channel, because everyone's styling starts from here.

---

### B1 — Demo data

**Owner:** Miles · **Roughly:** 3–4 hours · **After:** nothing
**Files:** `backend/app/seed.py`, `backend/tests/test_seed.py`

> *As someone demoing Cadence, I want a seeded deck with cards at every stage, so that I can show
> reviews, relapses, and learning cards without waiting days for them.*

- Keep "Spanish 101" exactly as it is, and create it first. It stays deck 1 with four new cards,
  so the [Lab 3 curl walk-through](LAB_3_PLAN.md#the-walk-through) still works.
- Add a second deck for the same user: **"Travel Spanish"**, described as "English → Spanish, with
  cards at every stage". Take one `utcnow()` at the start of the command, call it T, and set every
  time relative to it:

| Front | Back | `state` | `due_at` | `interval_days` | `ease_factor` | `step` | `lapses` | What it shows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| the airport | el aeropuerto | review | T − 4 days | 10 | 2500 | 0 | 0 | Story 1's "4 days overdue" row: Hard 12d, Good 30d, Easy 46d |
| the train station | la estación de tren | review | T − 1 day | 4 | 2500 | 0 | 0 | an ordinary review: 5d, 11d, 16d |
| the beach | la playa | review | T − 1 hour | 1 | 2500 | 0 | 0 | the minimums decide: 2d, 3d, 4d |
| the passport | el pasaporte | relearning | T − 5 min | 1 | 2300 | 0 | 1 | a lapsed card |
| the suitcase | la maleta | learning | T − 2 min | 0 | 2500 | 1 | 0 | Good graduates it to 1d |
| the ticket | el boleto | learning | T + 8 min | 0 | 2500 | 1 | 0 | not due yet, but shown early (learn-ahead) |
| the hotel | el hotel | review | T + 5 days | 12 | 2500 | 0 | 0 | not due: stays out of the session |
| the map | el mapa | review | T + 30 days | 40 | 2500 | 0 | 0 | not due |
| goodbye | adiós | new | null | 0 | 2500 | 0 | 0 | a new card |
| the library | la biblioteca | new | null | 0 | 2500 | 0 | 0 | a new card |
| the song | la canción | new | null | 0 | 2500 | 0 | 0 | a new card |

- Right after seeding, `GET /api/decks/2/due` returns `learning` [passport, suitcase, ticket],
  `review` [airport, train station, beach], and `new` [goodbye, library, song], so B2's
  `due_counts` for the deck is `{ "learning": 3, "review": 3, "new": 3 }`.
- **`flask seed --reset`** deletes the demo user, which cascades to their decks and cards, and
  seeds again with fresh times. Every time in the table is relative to when you seeded, so a
  rehearsal the day before the demo needs a reset on the day. Without `--reset`, nothing changes:
  it still does nothing if the demo user exists, and `test_seed_is_safe_to_run_twice` keeps
  passing.
- 🟢 **Optional: `flask time-travel --days N`**, with `--email` defaulting to the demo user. It
  moves `due_at` N days earlier on every card of that user's that isn't new, as if N days had
  passed. With it, the demo can show a card graduate to "1d" and come back. It's a CLI command
  only, never an HTTP route.

**Acceptance examples.** Run the commands with `app.test_cli_runner()`, as
`test_seed_is_safe_to_run_twice` does, then sign in as the seeded user with `login_as`.

| Given | When | Then |
| --- | --- | --- |
| an empty database | `flask seed` | two decks: Spanish 101 first with its four new cards, then Travel Spanish with the eleven cards above, in their states |
| a freshly seeded database | `GET /api/decks/<Travel Spanish>/due` | the three lists above, in that order |
| a seeded database | `flask seed` again | nothing changes |
| a seeded database where a card has been reviewed | `flask seed --reset` | that card is back in its seeded state, and there's still exactly one demo user |
| a seeded database and a second user with a scheduled card | `flask time-travel --days 1` | every non-null `due_at` of the demo user's is exactly one day earlier; new cards and the other user's card are unchanged |

**Done when:** the tests pass on SQLite and Postgres, coverage stays at 90% or above, and on a
fresh database `curl` shows the lists above.

---

### B2 — Due counts on decks

**Owner:** Nurzat · **Roughly:** 4–5 hours · **After:** nothing
**Files:** `backend/app/api/decks.py`, `backend/tests/test_deck_due_counts.py`

> *As a learner looking at my decks, I want to see how many cards are waiting in each one, so
> that I know where to start.*

- Move the three filter conditions in `get_due_cards()` into `_due_conditions(now)`, which
  returns one SQLAlchemy condition per list, and use it in both places. One definition is what
  keeps the counts equal to the lists.
- `_due_counts(deck_ids, now)`: one grouped query over `cards` that counts each condition per
  deck. `func.sum(case((condition, 1), else_=0))` works on both SQLite and Postgres. Then cap
  `review` at `REVIEWS_PER_SESSION` and `new` at `NEW_CARDS_PER_SESSION`. A deck missing from the
  result has no cards, so it gets zeros.
- Add `due_counts` to the JSON in all four routes that return a `Deck`. `list_decks()` runs one
  counts query for all of the user's decks, never one per deck (rule 5).
- One `utcnow()` per request, as in `get_due_cards()`.

**Acceptance examples.** Build cards with `make_card` and times relative to `utcnow()`, the way
`test_due_cards.py` does.

| Given | When | Then |
| --- | --- | --- |
| a deck with no cards | `GET /api/decks/:id` | `due_counts` is `{ "learning": 0, "review": 0, "new": 0 }` |
| one card in each of the four states, all due | `GET /api/decks` | `{ "learning": 2, "review": 1, "new": 1 }`: relearning counts as learning |
| a review due tomorrow and a learning card due in 30 minutes | `GET /api/decks/:id` | neither is counted |
| a learning card due in 15 minutes | `GET /api/decks/:id` | it's counted (learn-ahead) |
| 25 new cards and 205 due reviews | `GET /api/decks/:id` | `new` is 20 and `review` is 200 |
| each deck built in the rows above | `GET /api/decks/:id` and `GET /api/decks/:id/due` | `due_counts[k]` equals the length of `due[k]` for every `k` |
| a new deck, and a renamed one | `POST /api/decks`, `PATCH /api/decks/:id` | both responses include `due_counts` |
| five decks with cards | `GET /api/decks` | the same number of SQL statements as with one deck. Count them with the `before_cursor_execute` listener from `test_card_count_does_not_query_per_deck` |
| another user's due cards | `GET /api/decks` | never counted in my decks |

**Not in this chunk:** per-day limits ([L5](LAB_3_PLAN.md#decisions-we-made)), and a "next card
due at" time for decks with nothing due.

**Done when:** the tests pass on SQLite and Postgres, and after B1's seed,
`curl localhost:5001/api/decks` shows Travel Spanish at `{ "learning": 3, "review": 3, "new": 3 }`
and Spanish 101 at `{ "learning": 0, "review": 0, "new": 4 }`.

---

### B3 — Interval previews

**Owner:** Von · **Roughly:** 2–3 hours · **After:** nothing
**Files:** `backend/app/scheduler.py`, `backend/app/models/card.py`, `backend/app/api/decks.py`
(only the return in `get_due_cards()`), `backend/app/api/cards.py` (only the return in
`review_card()`), `backend/tests/test_interval_preview.py`

> *As a learner about to rate a card, I want each button to show when I'd see the card again, so
> that I know what my choice means.*

- `scheduler.py`, beside `answer_card()` and just as pure:

  ```python
  def preview_intervals(card: CardSchedule, now: datetime) -> dict[Rating, timedelta]:
      """How long after `now` the card would be due for each rating, if answered at `now`."""
      return {rating: answer_card(card, rating, now).due_at - now for rating in Rating}
  ```

- `models/card.py`: `Card.to_study_dict(now)` returns `to_dict()` plus `"intervals"`, keyed by
  each rating's string, with whole seconds as integers (`delta // timedelta(seconds=1)`). It takes
  `now` rather than reading the clock (rule 8).
- `get_due_cards()` returns `card.to_study_dict(now)` for every card, using the `now` it already
  has. `review_card()` returns `card.to_study_dict(now)` after it saves the new schedule, using its
  own `now`.

**Acceptance examples**

| Given | When | Then |
| --- | --- | --- |
| each card in the [reference table](#study-cards-gain-intervals-b3) | `preview_intervals()` | that row's numbers, as `timedelta`s |
| the same five cards, due, in a deck | `GET /api/decks/:id/due` | each card's `intervals` is that row's numbers, in seconds |
| a new card | `POST /api/cards/:id/review` with `good` | the response is `learning`, and its `intervals` is the "learning on step 1" row |
| any deck | `GET /api/decks/:id/cards` | no card has an `intervals` key |
| a learning card | `GET /api/decks/:id/due` | the card's row in the database is unchanged: previews save nothing |

**Done when:** the tests pass on SQLite and Postgres, and after B1's seed,
`curl localhost:5001/api/decks/2/due` shows the airport card with `"good": 2592000`.

---

### F1 — Study page

**Owner:** Duc · **Roughly:** 6–8 hours · **After:** Step 0b; Step 0c before writing CSS
**Files:** `src/pages/StudyPage.jsx`, `tests/StudyPage.test.jsx`, the F1 section of
`src/study.css`

> *As a learner, I want to see one card at a time, reveal the answer, and rate myself, so that I
> review actively.* This is Lab 3 Story 3's user story; F1 is the part a learner can see.

- `StudyPage`, the wrapper: reads `id` from the route, builds `api` as described under
  [`StudyView`](#studyview-f1), and renders `<div className="study"><StudyView key={id} ... /></div>`.
  Like `DeckDetailPage`, the `key` makes a different deck mount a fresh view. Layout, buttons, and
  panels come from the shared classes (rule 14).
- `StudyView` loads `getDeck(deckId)` and `getDueCards(deckId)` together, then renders the session
  in a child component that holds the reducer. Give that child a `key` from a load counter.
  **Study more** increments the counter, which fetches again and mounts a new session with a new
  reducer, so no new reducer action is needed. As in `DeckListPage`, derive "loading" by tagging
  the result with the request it answers, rather than setting state at the top of an effect.
- Four phases:
  - **loading**: a `role="status"` message.
  - **load failed**: on `not_found`, "This deck could not be found." and a way back; otherwise
    the message and a **Try again** button.
  - **studying**: the deck name, the number of cards left, `StudyCard`, and then either a
    **Show answer** button (before the reveal) or `RatingButtons` (after it).
  - **finished**: `SessionSummary`. It shows its empty state when nothing was due at the start.
- Rating follows [the response table](#how-the-study-page-handles-each-review-response):
  `answered` on a 200, `skipped` on a 409 or 404, the 401 left to the adapter, and an inline
  `role="alert"` for anything else. Guard it as rule 11 says: a ref set before the request and
  cleared in `finally`, plus `disabled` on the buttons while it's in flight.
- Keyboard: Space reveals, and 1–4 rate once the answer is showing. Listen on `window`, and ignore
  `event.repeat` and events from inputs, textareas, and buttons. A focused button already handles
  Enter and Space by itself.
- Pass `now()` wherever the reducer takes a `now`.

**Acceptance examples.** Use a fake `api` and a fixed clock. B1's cards make good fixtures.

| Given | When | Then |
| --- | --- | --- |
| one review card and one new card due | the page loads | the review card's front shows, its back doesn't, and there are no rating buttons |
| a card showing | **Show answer**, or Space | the back shows, and so do the four rating buttons |
| an answer showing | **Good** | `reviewCard` is called once with the card's id and `'good'`, and the next card shows |
| an answer showing | **Good** twice in quick succession, or 3 pressed twice | `reviewCard` is called once |
| an answer showing, and `reviewCard` rejects with `conflict` | **Good** | the next card shows, and the counts don't change |
| an answer showing, and `reviewCard` rejects with `network_error` | **Good** | the same card stays, still revealed, with an alert; **Good** again calls `reviewCard` again |
| the only card left, and `reviewCard` returns it as learning due in 10 minutes | **Good** | the same card shows again, unrevealed (learn-ahead) |
| the last card | any rating, returned as review | the summary shows, with the counts |
| nothing due | the page loads | the summary's empty state |
| `getDeck` rejects with `not_found` | the page loads | "This deck could not be found." and a way back |
| the summary showing | **Study more** | `getDueCards` is called again, and a new session starts |

**Not in this chunk:** undo, editing a card from the study page, and timers.

**Done when:** the tests pass, and in a browser, Travel Spanish on a freshly seeded database can
be studied from the first card to the summary.

---

### F2 — Card and rating buttons

**Owner:** Miles · **Roughly:** 3–4 hours · **After:** Step 0b; Step 0c before writing CSS
**Files:** `src/components/study/StudyCard.jsx`, `src/components/study/RatingButtons.jsx`,
`tests/StudyCard.test.jsx`, `tests/RatingButtons.test.jsx`, the F2 section of `src/study.css`

> *As a learner rating a card, I want to see when each choice would bring the card back, so that I
> rate honestly instead of guessing.*

- `StudyCard`: a panel with the front in Plus Jakarta Sans at heading size, and below a divider,
  the back once it's revealed. A `.badge-blue` shows the card's state: New, Learning, Relearning,
  or Review.
- `RatingButtons`: four buttons, Again, Hard, Good, and Easy, styled as the style guide's
  [rating buttons](#shared-pieces), with each one's key (1–4) as a hint. When `intervals` is
  there, each button shows `formatInterval()` of its value underneath, in tabular numbers, and its
  accessible name includes it ("Good, 1mo").
- Keep every behavior in [the props table](#the-study-components-0b-stubs-f2-and-f3-build-them):
  F1's tests depend on it.

**Acceptance examples**

| Given | When | Then |
| --- | --- | --- |
| `StudyCard` with `revealed` false | render | the front is visible, and the back isn't in the DOM |
| `StudyCard` with `revealed` true | render | both are visible |
| `RatingButtons` with a new card's intervals | render | the labels read `1m`, `6m`, `10m`, `4d` |
| `RatingButtons` with no `intervals` | render | four buttons with no interval text |
| `RatingButtons` | click **Hard** | `onRate('hard')`, once |
| `RatingButtons` with `disabled` | click **Hard** | `onRate` isn't called |

**Done when:** these tests pass, and so do F1's, with the real components in place of the stubs.

---

### F3 — Session summary

**Owner:** Duc · **Roughly:** 2–3 hours · **After:** Step 0b; Step 0c before writing CSS
**Files:** `src/components/study/SessionSummary.jsx`, `tests/SessionSummary.test.jsx`, the F3
section of `src/study.css`

> *As a learner finishing a session, I want to see how it went and what's next, so that I know
> when to come back.* This is the summary from Lab 3 Story 3's fourth acceptance test.

- **Session complete**: the total, and the count for each rating ("Again 1 · Hard 0 · Good 7 ·
  Easy 1"), then **Back to deck**.
- When `nextLearningDue` is set: "More cards in 25m" (via `formatInterval()`) and **Study more**.
  With Anki's default steps, every learning card is due within the 20-minute learn-ahead window,
  so the session usually keeps going instead. This case still needs to look right when it comes
  up.
- **Nothing to study right now**, when every count is zero, with **Back to deck**.

**Acceptance examples**

| Given | When | Then |
| --- | --- | --- |
| counts `{ again: 1, hard: 0, good: 2, easy: 0 }`, no next due time | render | "Session complete", 3 cards, and no **Study more** |
| a next due time 25 minutes after `now` | render | "More cards in 25m" and a **Study more** button |
| every count zero | render | "Nothing to study right now" |
| any summary | click **Back to deck** | `onExit` is called |

**Done when:** these tests pass, and so do F1's, with the real component in place.

---

### F4 — Deck pages: a way in, and the schedule on screen

**Owner:** Nurzat · **Roughly:** 5–6 hours · **After:** Steps 0b and 0c. Shows due counts once B2
merges
**Files:** `src/pages/DeckListPage.jsx`, `src/pages/DeckDetailPage.jsx`,
`src/components/CardRow.jsx`, `src/study/describeSchedule.js`, `src/ws4.css`,
`tests/describeSchedule.test.mjs`, `tests/CardRow.test.jsx`, `tests/DeckDetailView.test.jsx`,
`tests/DeckListView.test.jsx`

> *As a learner, I want to see what's due and start studying from my decks, so that I know where I
> stand and can start in one click.*

- `src/study/describeSchedule.js`: [both functions](#describeschedulecard-now-and-describeduecountsduecounts-f4),
  pure, with one test per row of their tables.
- `DeckDetailView`: a **Study now** primary button beside **+ Add card** whenever the deck has
  cards, labelled "Study now · 9" when `due_counts` is there (the sum of its three numbers). It
  calls a new `onStudy` prop, and the `DeckDetailPage` wrapper navigates to `/decks/:id/study`
  (rule 12). Under the title, `describeDueCounts(deck.due_counts)` in a `.badge-gold`, when it
  isn't null.
- `CardRow`: a `.badge-blue` with `describeSchedule(card, now)`. It takes a new `now` prop, which
  `DeckDetailView` reads once per load, so every row agrees.
- `DeckListView`: `describeDueCounts()` in a `.badge-gold` in each tile, beside the card count,
  and a **Study** text button in the tile's footer that calls a new `onStudyDeck(id)` prop.
- Leave everything else on these pages alone. WS4's behaviors, like the one-time "add your first
  card" flag, have to keep working, and the existing tests have to pass.

**Acceptance examples.** Render `DeckDetailView` and `DeckListView` with a fake `api`, the way
rule 12 intends.

| Given | When | Then |
| --- | --- | --- |
| a deck with cards and `due_counts` adding up to 9 | `DeckDetailView` renders | "Study now · 9"; clicking it calls `onStudy` |
| a deck with no cards | `DeckDetailView` renders | no Study button |
| a deck with cards but no `due_counts` | `DeckDetailView` renders | "Study now" with no number, and no counts badge |
| a review card due in 25 days | `CardRow` renders | "Review · in 25d" |
| a deck whose `due_counts` is `{ learning: 0, review: 0, new: 4 }` | `DeckListView` renders | "4 new" in its tile; **Study** calls `onStudyDeck` with its id |

**Done when:** the tests pass, and on a freshly seeded database, the deck list shows "4 new" on
Spanish 101 and "6 due · 3 new" on Travel Spanish.

---

### R — Walkthrough, docs, and release

**Owner:** Miles · **Roughly:** 4 hours, mostly on the last day · **After:** everything
**Files:** `README.md`, `code/Readme.md`, and the documents in `doc/` and `demo/`

- Run [the walkthrough](#the-walkthrough) on a fresh database, every step. Anything that fails
  goes back to the chunk that owns it, as an issue.
- `README.md` at the root: setup still says `flask init-db`, so switch it to `flask db upgrade` the
  way `code/Readme.md` already does; add the frontend test command; and say a line about study
  mode.
- `code/Readme.md`: a "Demo data" section covering `flask seed`, `--reset`, and `time-travel` if
  B1 built it.
- `doc/`: add the new pages' test cases to the STD, and change the SPPP's testing section from
  Jest to Vitest, which the Lab 3 plan left open ([L12](LAB_3_PLAN.md#decisions-we-made)). Both
  are `.docx` files, so these are edits by hand.
- Record the Iteration 2 demo video for `demo/`, as we did for Iteration 1.
- Open the `develop` → `main` release PR once the walkthrough passes.

**Done when:** the walkthrough passes on a fresh database, the docs are merged, and `main` has the
release.

---

## Schedule

One branch per chunk, off `develop`: `chore/ci-frontend-image-cache` (0a, already open as #44),
`feat/it2-0b-study-foundation`, `feat/it2-0c-style-foundation`, `feat/it2-b1-demo-seed`,
`feat/it2-b2-due-counts`, `feat/it2-b3-interval-preview`, `feat/it2-f1-study-page`,
`feat/it2-f2-card-buttons`, `feat/it2-f3-summary`, `feat/it2-f4-deck-pages`, and
`doc/it2-release`. Open a PR into `develop`, get one review, and merge as soon as it's green and
reviewed.

The dates are _TBD_ until we pin down the demo date.

| When | What should be true |
| --- | --- |
| **Day 0** | Plan agreed. 🔴 0a (#44) merged, so CI is green for everyone. 🔴 0b merged by the end of the day. |
| **Day 1** | 🔴 0c merged by midday. Nobody writes CSS before it does; F1–F3 start with logic and tests. B1 merged, so everyone can seed the demo deck. |
| **Day 2** | 🟡 F1 merged: a seeded deck can be studied in a browser from start to finish. B2, B3, F2, and F3 merged. |
| **Day 3** | F4 merged. Everything is on `develop`. |
| **Day 4** | R: the walkthrough on a fresh database, the docs, the video, and `develop` → `main`. |

How the chunks wait on each other:

```
0a ─────────────────────────────── every merge (CI has to be green)

0b ──┬── F1 ──┐
     ├── F2   ├─ logic and tests can start as soon as 0b merges
     ├── F3 ──┘
     └── F4
0c ───────────── every frontend chunk's CSS; F4 waits for it before touching ws4.css

B1, B2, B3       independent; the frontend renders without B2 and B3 (rule 10)

everything ───── R
```

### The walkthrough

This is the end-to-end check from decision [L14](LAB_3_PLAN.md#decisions-we-made): manual, in a
browser, on a fresh database. Run it from `code/`:

```bash
git pull origin develop
docker compose down -v && docker compose up -d --build
docker compose exec backend flask db upgrade
docker compose exec backend flask seed
```

Then open `localhost:3000`:

1. The sign-in page has the Cadence wordmark, the guide's two fonts, a blue **Sign in** button,
   and a gold focus ring as you Tab through it. Sign in as `demo@cadence.local` / `demo1234`.
   (0c)
2. The deck list sits under the navy header with the same buttons and panels as the sign-in page.
   It shows "4 new" on Spanish 101 and "6 due · 3 new" on Travel Spanish. (0c, B1, B2, F4)
3. Open Travel Spanish. Each card has a badge: "Review · due now" on the airport, "Review · in 5d"
   on the hotel, "Learning · in 8m" or less on the ticket (depending on how long ago you seeded),
   and "New" on goodbye. Click **Study now · 9**. (F4)
4. The first card is "the passport", with its answer hidden and no rating buttons. Press Space.
   "el pasaporte" shows, with Again 10m · Hard 15m · Good 1d · Easy 2d. Rate **Good**. (F1, F2,
   B3)
5. "the suitcase" is next, with Again 1m · Hard 10m · Good 1d · Easy 4d. Rate **Again**. It's due
   again in a minute, and once that minute is up it comes back ahead of the reviews and new cards
   still waiting, because a due learning card always goes first. (F1, Lab 3 Story 3)
6. "the airport" shows Again 10m · Hard 12d · Good 1mo · Easy 1.5mo: Story 1's four-days-overdue
   example, on screen. Rate **Good**.
7. Keep rating until the summary appears. With the default steps, every learning card comes back
   within the learn-ahead window, so the session ends when they've all graduated. The summary
   shows the count for each rating. (F3)
8. **Back to deck.** The badges have moved: the airport says "Review · in 30d", and the cards you
   graduated say "Review · in 1d". The deck list now shows Travel Spanish as "All caught up". (F4)
9. Open Spanish 101 and study it. Rate the first card **Good**, then refresh the page. The new
   session doesn't start with that card any more: the answer was saved, so it's a learning card
   now, and it comes back after the other three.
10. On one card, double-click **Good** with the browser's Network tab open. There's one
    `POST /review`, not two. (Rule 11)
11. Sign out, sign back in, and open Travel Spanish. Everything from step 8 is still there.
12. Sign up as a second user and go to `/decks/2/study`. The page says the deck could not be
    found.
13. 🟢 Optional, if B1 built it: `docker compose exec backend flask time-travel --days 1`, then
    refresh the deck list. Travel Spanish shows the cards graduated in step 7 as due again.

The [Lab 3 curl walk-through](LAB_3_PLAN.md#the-walk-through) should still pass too: B1 leaves
deck 1 as it was.

### Things that could go wrong

| Risk | What we do about it |
| --- | --- |
| CI stays red on `develop` | Nothing can merge cleanly until it's green, so 0a goes first, on Day 0. If `no-cache-filters` doesn't fix it, bump the nginx tag in the same PR. |
| Someone styles a page before 0c lands | It gets restyled twice. Nobody writes CSS before 0c merges; write logic and tests first. |
| A page drifts from the style guide | Rule 14 and 0c's grep check catch stray colors and fonts. Step 1 and 2 of the walkthrough check the rest by eye. |
| B2 or B3 lands late | The frontend renders without `due_counts` and `intervals` (rule 10). The demo loses the counts and the button labels, nothing else. If either has no PR by Day 2, raise it in the channel and whoever is free picks it up. |
| B2 and B3 conflict in `api/decks.py` | They touch different lines: B2 the deck routes and the filter conditions, B3 the `jsonify` at the end of `get_due_cards()`. Whoever merges second rebases. |
| A double-click answers a learning card twice | Rule 11 and F1's acceptance tests. Step 10 of the walkthrough checks it in a real browser. |
| The browser's clock and the server's disagree | A card the page thinks is due can come back 409. The page skips it and moves on, which is the designed behavior. |
| Times in the seed data have drifted by demo day | Run `flask seed --reset` on the day. |
| The local database is missing the Lab 3 columns | `docker compose exec backend flask db upgrade` |
| A component test can't find a button | Query by role and the accessible name from [the props table](#the-study-components-0b-stubs-f2-and-f3-build-them), not by class or text inside a span. |

---

## Decisions we made

These are numbered P1–P11 so they don't collide with Iteration 1's D1–D7 or Lab 3's L1–L14, which
all still stand.

- **P1 — The session reducer is used as it is.** `session.js` is tested against Anki's rules and
  is a Lab 3 deliverable. The page adapts to it. `useReducer`'s initializer argument and a remount
  for **Study more** cover everything we would otherwise have added an action for.
- **P2 — The backend sends intervals as seconds, and the frontend only formats them.** That
  follows rule 6: there's one copy of the algorithm. Seconds keep the API free of display choices,
  and `formatInterval()` holds all of them.
- **P3 — Previews only on study responses.** `intervals` costs four scheduler calls per card. The
  study page needs them and the card list doesn't, so `Card` keeps the shape it has everywhere
  else.
- **P4 — Due counts share the due-list conditions.** `_due_conditions()` is the only definition,
  and a test checks that the counts equal the lists. A badge that says 9 when the session serves 8
  would be the first thing anyone noticed in a demo.
- **P5 — The page guards against double answers.** The 409 from L7 protects review cards only. A
  duplicate answer on a learning card falls inside the learn-ahead window and is accepted, so the
  client has to stop it (rule 11).
- **P6 — Typed-answer mode is out of Iteration 2.** The study page works in flip mode, which is
  Anki's default. The demo doesn't need typed answers, and leaving them out removes the only chunk
  that waited on unfinished Lab 3 work (Story 4's checker isn't on `develop`).
- **P7 — The study page is a route, `/decks/:id/study`, not a modal.** A refresh or a link puts you
  back in a session. That's safe because every answer is already saved (Story 5): a refresh loses
  only that session's counts.
- **P8 — Demo data goes in `flask seed`, in a second deck.** Deck 1 is unchanged, so the Lab 3
  walk-through and its tests still hold. `--reset` exists because the seeded times are relative
  to when you seed.
- **P9 — Study components live in `src/components/study/`, and the study page's layout in
  `src/study.css`.** Everything else about how it looks comes from the shared classes in
  `styles.css`, so the study page needs no copy of the deck pages' CSS.
- **P10 — Anki's keyboard shortcuts.** Space reveals, and 1–4 rate. Anyone who has used Anki
  already knows them.
- **P11 — One design system: Inter and Plus Jakarta Sans, blue and gold, all in `styles.css`.**
  WS3 and WS4 styled their pages independently, which is why the sign-in page and the deck pages
  don't match. One set of tokens, and shared classes every page uses, is the smallest change that
  fixes it and keeps it fixed. The fonts load with a `<link>` rather than an npm package (rule 13)
  and fall back to the system font.

## Out of scope

Don't spend time on any of this: typed-answer mode and anything built on it (Lab 3 Story 4, AI
grading, accepting more than one answer); the review-history table and everything that needs it
(per-day limits, stats, streaks, heatmaps); undo; editing a card from the study page; a "next due"
time for decks with nothing due; per-user settings; multiple-choice review (it's in the README's
feature list, but it's a later iteration); dark mode; icons beyond the text symbols already in use;
a CSS framework or component library; AI card generation and duplicate detection, which need their
own plan; fuzz; FSRS; per-deck settings; automated browser tests (L14); and seeding the deployed
database on Render.

---

## Working with an AI agent

Like the earlier plans, this one is written so you can hand it to Claude Code (or a similar tool)
and get work that fits with everyone else's. Start a session in `code/` on your chunk's branch:

```
Read plans/FINALIZE_ITERATION_2_PLAN.md in the code/ directory, all of it. It builds
on plans/LAB_3_PLAN.md and plans/ITERATION_1_PLAN.md -- read their "Rules that keep
the code consistent", "API contract changes" and "Security basics" sections too.

Implement chunk <ID>: <title>, from "Chunks in detail". Work test-first: write the
tests from my chunk's acceptance examples, run them and show me they fail, then
implement until they pass.

Rules:
- Follow "API contract changes", "Frontend contracts", and "Style guide" exactly. If
  something there looks wrong, stop and tell me instead of changing it -- other
  people are writing code against it.
- Only create or edit the files listed under my chunk. If you need something another
  chunk owns, tell me instead of writing it.
- Don't change src/study/session.js or src/study/constants.js, and don't add packages
  or migrations.
- In CSS, use the style guide's tokens and shared classes. Don't add colors or fonts.

Stop when my chunk's "Done when" line passes, and show me the output that proves it.
```

A few things that make this go better:

- **Give it the whole file, not a snippet.** The contracts and the file list are what keep four
  people's work compatible.
- **One chunk per session.** An agent told to "finish study mode" will rewrite the reducer, the
  contract, and someone else's component to fit whatever it wrote last.
- **For a frontend chunk, have it read the existing pattern first.** `DeckDetailPage.jsx`,
  `decks.js`, and `CardRow.test.jsx` show how this codebase builds pages, clients, and component
  tests. Code that follows them is much easier to review.
- **Ask for proof.** Each "Done when" line describes something you can run. "It should work now"
  isn't that.
- **Read what it wrote before you open the PR.** You'll be reviewing each other's, and presenting
  the demo.
