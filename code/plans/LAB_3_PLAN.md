# Cadence — Lab 3 Plan: Study Mode Foundations

**Status:** Draft 1, for team review. Nothing here is final until we agree on it in the channel.
**Dates:** _TBD_ → Lab 3 due _TBD_
**Team:** _TBD_, one owner per story

## What we're building

Lab 3 asks each of us to build a small user story test-first and show the tests failing, then
passing, then passing inside Docker. We're using it to build the core of Iteration 2's study mode:
five stories that each stand alone for the lab and fit together into one feature afterwards.

1. **Scheduler** — Anki's scheduling algorithm as one pure Python function. Given a card and a
   rating, when is it next due?
2. **Due cards** — `GET /api/decks/:id/due`. Which cards should I study right now?
3. **Study session** — a frontend reducer that runs a session: which card is next, reveal, rate,
   bring learning cards back when they're due.
4. **Typed answer** — a frontend function that checks a typed answer and suggests a rating.
5. **Save a review** — `POST /api/cards/:id/review`. Run the scheduler on a rating and save the
   result.

At the end of the lab, with `curl` alone, you can log in, ask for a deck's due cards, rate one,
and see its next due time saved exactly where Anki would put it. The frontend has the two tested
modules the study page will be built from.

The study page itself is **not** in the lab. It's the first thing after it — see
[After the lab](#after-the-lab).

## Contents

- [Who's doing what](#whos-doing-what)
- [Where the code is today](#where-the-code-is-today)
- [Architecture](#architecture)
- [Database changes](#database-changes)
- [API contract changes](#api-contract-changes)
- [Security basics](#security-basics)
- [Stories in detail](#stories-in-detail)
- [Lab 3 deliverables](#lab-3-deliverables)
- [Schedule](#schedule)
- [Decisions we made](#decisions-we-made)
- [Out of scope](#out-of-scope)
- [After the lab](#after-the-lab)
- [Working with an AI agent](#working-with-an-ai-agent)

---

## Who's doing what

| # | Story | Lives in | Owner | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| **0a** | **Backend foundation** — scheduling columns and migration, the scheduler's types and settings, a test fixture | backend | Miles | nothing | S |
| **0b** | **Frontend foundation** — Vitest and React Testing Library, the existing tests moved over, two constants | frontend | _TBD_ | nothing | S |
| **1** | **Scheduler** — Anki's algorithm | `backend/app/scheduler.py` | _TBD_ | 0a | M |
| **2** | **Due cards** — `GET /api/decks/:id/due` | `backend/app/api/decks.py` | _TBD_ | 0a | S |
| **3** | **Study session** — the session reducer | `frontend/src/study/session.js` | _TBD_ | 0b | M |
| **4** | **Typed answer** — the answer checker | `frontend/src/study/typedAnswer.js` | _TBD_ | 0b | S |
| **5** | **Save a review** — `POST /api/cards/:id/review` | `backend/app/api/cards.py` | _TBD_ | 0a, plus 1 for its last two tests | S |

Step 0 is small on purpose and lands first, because every story builds on it — the same job WS0
did in Iteration 1. Its two halves don't depend on each other, so two people can do them at the
same time: 0a unblocks the backend stories and 0b the frontend ones. 0a also exists so stories 2
and 5 don't wait on each other: both need the new columns, so neither of them owns the columns.

Either half can go to someone who also has a story. 0b in particular is an hour or two of work,
and fits whoever takes story 3 or 4.

---

## Where the code is today

Iteration 1 left a working app: sign up, log in, and manage decks and cards. What this lab builds
on:

| File | What's there |
| --- | --- |
| `backend/app/models/card.py` | `Card` with `front` and `back`. No scheduling data yet |
| `backend/app/models/base.py` | `utcnow()` and `iso()` |
| `backend/app/api/decks.py` | deck CRUD and `_own_deck_or_404()` |
| `backend/app/api/cards.py` | card CRUD and `_own_card_or_404()`, which checks ownership through the deck |
| `backend/app/errors.py` | the closed error table, `json_object()`, `validation_error(field=)`, `conflict()` |
| `backend/migrations/` | Flask-Migrate, with one hand-written migration, `0001_initial_schema` |
| `backend/tests/conftest.py` | in-memory SQLite, and the fixtures `client`, `make_user`, `login_as`, `make_deck(user, cards=[(front, back)])` |
| `frontend/src/api/` | `client.js` (the only `fetch`) and the `createDecksApi(request)` adapter |
| `frontend/tests/*.test.mjs` | 11 tests on Node's built-in test runner (`node --test`), none of them for React components. Step 0b moves them to Vitest |

Four things CI enforces that shape this plan:

- **Backend coverage has to stay at 90% or above.** The SQLite test job fails below it, so every
  branch you write needs a test.
- **Backend tests also run against Postgres.** Something that passes on SQLite can still fail
  there, usually over dates or types.
- **Migrations have to match the models.** The Migrations job runs `flask db upgrade`, then
  `flask db check` (which fails if the models and the migrated schema differ), then downgrades to
  empty and back up. A model change without a migration, or a broken `downgrade()`, can't merge.
- **Frontend:** `eslint`, `npm test`, and `npm run build` all have to pass. `eslint` covers
  `tests/` too.

Nothing needs to change in either Dockerfile for the lab. Both `dev` images copy the whole folder,
tests included; compose bind-mounts the source over it; and `pytest` is already in
`requirements.txt`. Say so in your report, since the lab asks you to modify the Dockerfile "if
needed". Details are under [Lab 3 deliverables](#lab-3-deliverables).

---

## Architecture

### New and changed files

```
code/
  plans/
    ITERATION_1_PLAN.md
    LAB_3_PLAN.md                        # this file
  Readme.md                              # 0a: database section -> flask db upgrade
  backend/
    app/
      models/
        base.py                          # 0a: + as_utc()
        card.py                          # 0a: + six scheduling columns, Card.schedule,
                                         #     state and due_at in to_dict()
      scheduler.py                       # 0a: types, settings, stub    1: answer_card()
      api/
        decks.py                         # 2: + GET /api/decks/<id>/due
        cards.py                         # 5: + POST /api/cards/<id>/review
    migrations/versions/
      <date>_0002_card_scheduling.py     # 0a
    tests/
      conftest.py                        # 0a: + make_card fixture
      test_card_schedule.py              # 0a
      test_scheduler.py                  # 1
      test_due_cards.py                  # 2
      test_review.py                     # 5
  frontend/
    package.json, package-lock.json      # 0b: + vitest, jsdom, @testing-library/react;
                                         #     "test" runs vitest
    eslint.config.mjs                    # 0b: lint .jsx test files too
    src/study/
      constants.js                       # 0b: RATINGS, LEARN_AHEAD_MS
      session.js                         # 3
      typedAnswer.js                     # 4
    tests/
      decks.test.mjs                     # 0b: moved to Vitest
      decks-client.test.mjs              # 0b: moved to Vitest
      CardRow.test.jsx                   # 0b: the first component test
      session.test.mjs                   # 3
      typedAnswer.test.mjs               # 4
```

Each file belongs to one story. If you need a file someone else owns, message them instead of
editing it.

### Shared files

| File | Why it's shared | Rule |
| --- | --- | --- |
| `backend/app/models/card.py` | story 2 queries the new columns, story 5 writes them | Step 0a only. Nobody else edits it during the lab |
| `backend/app/scheduler.py` | story 2 imports its settings, story 5 calls `answer_card()` | Step 0a writes the interface, then story 1 owns the file. The interface is frozen — see [The scheduler interface](#the-scheduler-interface) |
| `backend/tests/conftest.py` | stories 2 and 5 both need cards in a given state | Step 0a adds `make_card`. Need another fixture? Put it in your own test file |
| `backend/app/errors.py` | story 5 returns 409 and 422 | Unchanged. We reuse `conflict()` and `validation_error()`, and add no codes |
| `frontend/src/study/constants.js` | stories 3 and 4 both use the ratings | Step 0b only |
| `frontend/package.json` + `package-lock.json` | a new package changes both | Step 0b only. Nobody adds a frontend package during the lab |

Nobody touches these during the lab: `app/api/__init__.py` (the new routes go in the existing
`decks` and `cards` blueprints, so nothing new needs registering), `requirements.txt`, and
`App.jsx`.

### How the pieces fit

```
Study page (after the lab)
  │
  │ 1. GET /api/decks/3/due ─────────────▶ decks.py (2) ── three queries on state and due_at
  │    ◀── { learning: [...], review: [...], new: [...] }
  │
  │ 2. session.js (3) picks the next card; the learner reveals it
  │    (in typed mode, typedAnswer.js (4) suggests a rating)
  │
  │ 3. POST /api/cards/9/review {rating} ─▶ cards.py (5)
  │                                          ├─ your card, or 404
  │                                          ├─ not due yet? 409
  │                                          ├─ card.schedule = answer_card(card.schedule, rating, now)  (1)
  │                                          └─ commit
  │    ◀── the updated Card { state, due_at, ... }
  │
  │ 4. session.js (3) puts it back in the queue if it's still learning, then back to 2
```

### Testing stack

| What's tested | Tool | Where | Status |
| --- | --- | --- | --- |
| Backend logic and API | pytest, with Flask's test client | `backend/tests/` | in place. Stories 1, 2, 5 |
| Frontend logic | Vitest | `frontend/tests/*.test.mjs` | Step 0b. Stories 3, 4 |
| React components | Vitest + React Testing Library, in a simulated browser (jsdom) | `frontend/tests/*.test.jsx` | Step 0b sets it up with one test. The study page uses it after the lab |
| Behavior (BDD) | Given / When / Then scenarios in this plan, each one a test named after it | | no extra tool (L13) |
| The whole app in a browser | a manual walkthrough at the end of each iteration | | no browser automation (L14) |
| The whole stack in Docker | CI's smoke test: compose up, migrate, health check | `.github/workflows/ci.yml` | in place |

Name each test after its scenario, so the list of tests reads like the acceptance table:
`test_good_on_a_10_day_card_is_due_in_25_days` in pytest, or
`test('rating before revealing changes nothing', ...)` in Vitest. That naming is the BDD half of
the lab.

### Rules that keep the code consistent

The five rules in the [Iteration 1 plan](ITERATION_1_PLAN.md#rules-that-keep-the-code-consistent)
still apply: thin routes, one `fetch`, tests that exercise what they name, `json_object()`, and
counting in SQL. Four more for this lab:

6. **There is one copy of the algorithm.** Only `app/scheduler.py` decides intervals and due
   times. Routes call it, and the frontend never recomputes one. If the UI later needs to show
   "10m" or "4d" on the buttons, the backend sends it.
7. **The scheduler is pure.** It imports nothing from Flask, SQLAlchemy, or `app.models`. It takes
   a `CardSchedule`, a rating, and `now`, and returns a new `CardSchedule`. That's what lets its
   tests be plain `assert`s with no database.
8. **Time is passed in, and it's always UTC.** Nothing in `scheduler.py` or `session.js` reads the
   clock. A route calls `utcnow()` once and passes it down; a test passes a fixed time. Datetimes
   read back from the database go through `as_utc()` first, because SQLite returns them without a
   timezone, and subtracting one of those from an aware datetime raises `TypeError`.
   `Card.schedule` does this for you.
9. **Pure frontend modules stay pure.** `src/study/*.js` imports nothing from React or
   `src/api/`, and has no JSX. Its tests then run in Vitest's plain Node environment: fast, and
   with no simulated browser to set up. Only component tests (`*.test.jsx`) use jsdom.

---

## Database changes

Step 0a adds six columns to `cards`. They mirror Anki's own card fields.

| Column | Type | Default | Meaning |
| --- | --- | --- | --- |
| `state` | varchar(16), not null | `'new'` | `new`, `learning`, `review`, or `relearning` |
| `due_at` | timestamp with time zone, null | null | when the card is next due. Null only while `new` |
| `interval_days` | integer, not null | 0 | the review interval. While relearning, the interval the card goes back to |
| `ease_factor` | integer, not null | 2500 | in thousandths, so 2500 = 250%. An integer, the way Anki stores it, so ease changes are exact |
| `step` | integer, not null | 0 | which learning or relearning step the card is on, counting from 0 |
| `lapses` | integer, not null | 0 | how many times the card has been failed from review |

- Declare each column with both `default=` (for rows created in Python) and `server_default=` (so
  the migration fills in existing rows). Existing cards become `new`, which is what they are.
- No new index. The existing `ix_cards_deck_id` already narrows every query to one deck's cards.
- Editing a card's text doesn't touch its schedule. Anki behaves the same way.

### After Step 0 merges

**Your database (0a).** After Step 0a merges, a database created with `flask init-db` is missing
the new columns, because
`create_all()` doesn't add columns to a table that already exists. Either run

```bash
docker compose exec backend flask db upgrade      # keeps your data
```

or start over with `docker compose down -v`, `up`, `init-db`, and `seed`. Render runs
`flask db upgrade` on every deploy (`preDeployCommand` in `render.yaml`), so the deployed database
takes care of itself.

**Your frontend container (0b).** After Step 0b merges, the frontend container still has the old
`node_modules`, without Vitest. Rebuild it with `docker compose up --build -V`; the `-V` recreates
that volume, the same fix the root README describes.

---

## API contract changes

**Same rule as Iteration 1:** agree on this before writing code. If something here turns out to
be wrong, say so in the channel and we change it together. Don't change it quietly on your branch.

Everything in the [Iteration 1 contract](ITERATION_1_PLAN.md#api-contract) stays as it is. The
changes:

### The `Card` object gains two fields

```jsonc
{
  "id": 9,
  "deck_id": 3,
  "front": "la biblioteca",
  "back": "the library",
  "state": "learning",               // new | learning | review | relearning
  "due_at": "2026-10-01T14:10:00Z",  // null while the card is new
  "created_at": "2026-09-17T14:00:00Z",
  "updated_at": "2026-10-01T14:00:00Z"
}
```

The change is additive, so existing frontend code keeps working. The other four scheduling
columns stay internal: the frontend has no use for them, and rule 6 says it shouldn't compute
with them.

### Ratings

On the wire and in JavaScript, a rating is one of four lowercase strings: `"again"`, `"hard"`,
`"good"`, `"easy"`. Anki numbers its buttons 1–4. We don't use numbers anywhere.

### `GET /api/decks/:id/due` — Story 2

Login required. Someone else's deck, or one that doesn't exist, answers 404.

```json
{ "learning": [Card, ...], "review": [Card, ...], "new": [Card, ...] }
```

All three keys are always present. A list with nothing in it is `[]`.

| List | Contains | Order | At most |
| --- | --- | --- | --- |
| `learning` | `learning` and `relearning` cards with `due_at` ≤ now + 20 minutes | `due_at`, then `id` | no limit |
| `review` | `review` cards with `due_at` ≤ now | `due_at` (most overdue first), then `id` | 200 |
| `new` | `new` cards | `id` (the order they were created) | 20 |

The 20 minutes is Anki's "learn ahead limit". When there's nothing else to study, Anki shows a
learning card up to 20 minutes early rather than make you wait for it.

### `POST /api/cards/:id/review` — Story 5

Login required. The body is `{"rating": "good"}`, and success is 200 with the updated `Card`.

| Status | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` | the body isn't a JSON object |
| 401 | `unauthorized` | signed out |
| 404 | `not_found` | the card doesn't exist, or isn't yours |
| 409 | `conflict` | **the card isn't due yet**: a `review` card with `due_at` after now, or a `learning` or `relearning` card due more than 20 minutes from now |
| 422 | `validation_error`, with `field: "rating"` | `rating` is missing, or isn't one of the four |

The checks run in this order: login, ownership, body, rating, then due.

The 409 is new. Until now `conflict` only meant "email already registered". No code is added, so
the errors table stays closed, but the frontend has to handle `conflict` on this endpoint.
Decision [L7](#decisions-we-made) explains why the check exists.

### Validation rules: additions

| Field | Rule |
| --- | --- |
| `rating` | exactly one of `again`, `hard`, `good`, `easy` |

### The scheduler interface

It isn't HTTP, but three stories code against it, so it's part of the contract. Step 0a writes
this into `backend/app/scheduler.py`. Story 1 fills in `answer_card()` and changes nothing else
here.

```python
class CardState(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class Rating(StrEnum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


@dataclass(frozen=True)
class CardSchedule:
    state: CardState
    due_at: datetime | None   # UTC-aware. None only while new
    interval_days: int
    ease_factor: int          # thousandths: 2500 = 250%
    step: int
    lapses: int


def answer_card(card: CardSchedule, rating: Rating, now: datetime) -> CardSchedule:
    """The card's schedule after the learner answers it with `rating` at `now`."""
    raise NotImplementedError  # Story 1
```

Plus the settings, as module constants named after Anki's deck-option labels:

```python
# Anki's default deck options.
LEARNING_STEPS = (timedelta(minutes=1), timedelta(minutes=10))
GRADUATING_INTERVAL_DAYS = 1
EASY_INTERVAL_DAYS = 4
RELEARNING_STEPS = (timedelta(minutes=10),)
MINIMUM_INTERVAL_DAYS = 1
MAXIMUM_INTERVAL_DAYS = 36500
STARTING_EASE = 2500
EASY_BONUS = 1.3
HARD_INTERVAL = 1.2
NEW_INTERVAL = 0.0            # a failed review card's interval is multiplied by this

# Fixed in Anki's code rather than set per deck.
EASE_AGAIN = -200
EASE_HARD = -150
EASE_EASY = 150
MINIMUM_EASE = 1300

# How much one session serves. Story 2 uses these. LEARN_AHEAD is mirrored in
# frontend/src/study/constants.js -- change both together.
LEARN_AHEAD = timedelta(minutes=20)
NEW_CARDS_PER_SESSION = 20
REVIEWS_PER_SESSION = 200
```

`Card.schedule`, in `models/card.py`, converts between a database row and a `CardSchedule`. That's
what lets the heart of story 5 read:

```python
card.schedule = answer_card(card.schedule, rating, now)
db.session.commit()
```

`models/card.py` imports from `scheduler.py`, never the other way round (rule 7), so there's no
import cycle.

---

## Security basics

All five from [Iteration 1](ITERATION_1_PLAN.md#security-basics) still apply. The ones this lab
touches:

- **Always filter by the logged-in user.** Story 2 goes through `_own_deck_or_404()` and story 5
  through `_own_card_or_404()`. Both need a test where user A asks about user B's deck or card
  and gets 404. For story 5, also check that B's card was **not** changed.
- **No raw SQL.** The due-card queries are ordinary SQLAlchemy filters.
- **Validate on the server.** The backend checks `rating`, even though the frontend only ever
  sends one of four buttons.

---

## Stories in detail

Every story is built test-first. Each one gives its user story and its acceptance examples in
Given / When / Then form: they're the BDD half of your Lab 3 report and the test list for your
agent. Name each test after its row (see [Testing stack](#testing-stack)).
[Lab 3 deliverables](#lab-3-deliverables) has the red/green routine.

### Step 0a — Backend foundation 🔴 blocks stories 1, 2, and 5

**Owner:** Miles · **Due:** Day 0 · **Roughly:** 3 hours

- `app/models/base.py`: `as_utc(value)`, which returns an aware UTC datetime (assuming UTC when
  there's no timezone) or `None`. Have `iso()` use it.
- `app/scheduler.py`: exactly [the interface above](#the-scheduler-interface) — the two enums,
  `CardSchedule`, the settings, and `answer_card()` raising `NotImplementedError`.
- `app/models/card.py`: the six columns from [Database changes](#database-changes); `state` and
  `due_at` in `to_dict()`; and a `schedule` property. Its getter builds a `CardSchedule` from the
  row, passing `due_at` through `as_utc()`. Its setter copies one back onto the row.
- Migration `0002_card_scheduling`: against a database at `0001`, run
  `docker compose exec backend flask db migrate --rev-id 0002_card_scheduling -m "card scheduling"`
  (the bind mount puts the file in your working tree), then **read what it wrote** (see
  `doc/CICD.md`). You should see six added columns with server defaults, and a `downgrade()` that
  drops all six. Rename the file to `<date>_<time>_0002_card_scheduling.py` to match `0001`'s
  name.
- `tests/conftest.py`: `make_card(deck, front="q", back="a", **schedule)`, which creates a card
  with any of the six fields set. For example,
  `make_card(deck, state="review", due_at=utcnow() - timedelta(days=3), interval_days=10)`.
- `tests/test_card_schedule.py`: a new card defaults to `state` `new`, `due_at` null,
  `ease_factor` 2500, and 0 for the rest; the card JSON includes `state` and `due_at`; `card.schedule` survives a round trip through the database with
  an aware `due_at`; and `as_utc()` handles naive, aware, and `None`.
- `code/Readme.md`: replace "There are no migrations this iteration (decision D3)" with the
  `flask db upgrade` instructions.

**Done when:** CI is green, including the Migrations job; `flask db upgrade` works on a database
from Iteration 1; and `curl` on a deck's cards shows `"state": "new", "due_at": null`. Post in the
channel when it's merged.

---

### Step 0b — Frontend foundation 🔴 blocks stories 3 and 4

**Owner:** _TBD_ · **Due:** Day 0 · **Roughly:** 2 hours

- `npm install -D vitest jsdom @testing-library/react`, picking a Vitest release that supports
  Vite 7 (npm complains if the peer versions clash). Commit `package.json` and
  `package-lock.json` together; the Dockerfile's `npm ci` fails if they disagree.
- `package.json`: `"test": "vitest run"`.
- Move the two existing test files to Vitest by swapping `import test from 'node:test'` for
  `import { test } from 'vitest'`. Their `node:assert/strict` assertions keep working inside
  Vitest, so nothing else changes.
- `tests/CardRow.test.jsx`, starting with the line `// @vitest-environment jsdom`: a card's front
  and back are shown, and clicking Delete asks for confirmation. `CardRow` takes plain props and
  needs no login state, which makes it the simplest component to prove the setup on. We import
  Vitest's functions rather than turning on its globals, so React Testing Library can't clean up
  on its own: call its `cleanup()` in an `afterEach`.
- `eslint.config.mjs`: extend the `tests/**` block to `.jsx`, with JSX parsing and the
  `react/jsx-uses-vars` rule. Without that, eslint silently skips `.jsx` test files.
- `src/study/constants.js`: `RATINGS = ['again', 'hard', 'good', 'easy']` and
  `LEARN_AHEAD_MS = 20 * 60 * 1000`, with a comment pointing at the backend's `LEARN_AHEAD`.
- Optional, in the same lockfile change: move the eslint packages into `devDependencies`, as the
  comment at the top of `eslint.config.mjs` asks, so anyone can run eslint locally. CI's
  `npm install --no-save` step can then go.

**Done when:** `npm test` runs all 12 tests under Vitest; CI's frontend job is green; and after
`docker compose up --build -V`, `docker compose exec frontend npm test` passes. Post in the
channel when it's merged.

---

### Story 1 — Scheduler (Anki's algorithm)

**Owner:** _TBD_ · **Roughly:** 6–8 hours · **After:** Step 0a
**Files:** `backend/app/scheduler.py` (fill in `answer_card()`, plus any private helpers),
`backend/tests/test_scheduler.py`

> *As a learner, I want each card's next review scheduled from how well I recalled it, so that I
> see hard cards often and easy ones rarely.*

This is Anki's default scheduler with Anki's default settings. That scheduler is based on the
classic SM-2 algorithm; FSRS, Anki's newer optional scheduler, is off by default and out of scope.
The rules below were checked against Anki's source, in `rslib/src/scheduler/states/` of
[ankitects/anki](https://github.com/ankitects/anki/tree/main/rslib/src/scheduler/states).

**Write it from these rules, not by translating Anki's Rust.** Anki is AGPL-licensed (decision
D5). Matching its behavior is fine; porting its code line by line isn't.

#### New and learning cards

A `new` card is answered as if it were on the first learning step (step 0).

| Card is on | Again | Hard | Good | Easy |
| --- | --- | --- | --- | --- |
| step 0 (1m), or `new` | step 0, due in 1m | step 0, due in 5m30s | step 1, due in 10m | `review`, 4 days |
| step 1 (10m) | step 0, due in 1m | step 1, due in 10m | `review`, 1 day | `review`, 4 days |

- Hard on the first step is the average of the first two steps: (1m + 10m) / 2 = 330 seconds. On
  any later step, Hard repeats the current step.
- Moving to review ("graduating") sets `ease_factor` to `STARTING_EASE`, `step` to 0, and
  `interval_days` to 1 or 4. `due_at` is now plus that many days.
- Learning never changes `lapses`.

#### Review cards

`I` is `interval_days`, `E` is `ease_factor` / 1000, and `L` is the number of whole days overdue:
`max(0, floor((now − due_at) / 1 day))`. Work out Hard, then Good, then Easy, whichever button was
pressed, because each one's minimum depends on the one before.

| Rating | New `interval_days` | `ease_factor` | Also |
| --- | --- | --- | --- |
| Again | `max(round(I × NEW_INTERVAL), MINIMUM_INTERVAL_DAYS)`, which is 1 | − 200, not below 1300 | goes to `relearning`, step 0, due in 10m; `lapses` + 1 |
| Hard | `round(I × 1.2)`, at least I + 1 | − 150, not below 1300 | |
| Good | `round((I + L/2) × E)`, at least Hard + 1 | unchanged | |
| Easy | `round((I + L) × E × 1.3)`, at least Good + 1 | + 150, no ceiling | |

Every interval is capped at `MAXIMUM_INTERVAL_DAYS`, and so are the minimums, so at the cap Hard,
Good, and Easy can all be 36500. For Hard, Good, and Easy the card stays in `review` and `due_at`
is now plus the new interval.

#### Relearning cards

A failed review card relearns for one 10-minute step, then goes back to review. While it's
relearning, `interval_days` holds the interval it goes back to: 1 day, set when it failed.

| Again | Hard | Good | Easy |
| --- | --- | --- | --- |
| step 0, due in 10m | same step, due in 15m | `review`, due in `interval_days` days | `review`, `interval_days` + 1, due in that many days |

- Hard with only one step is 1.5× that step: 15 minutes.
- Again while relearning doesn't change `ease_factor` or `lapses` (they already changed when the
  review failed). It recomputes `interval_days` the same way a failed review does, which with our
  settings gives 1 again.
- Going back to review sets `step` to 0.

#### Matching Anki's arithmetic

Two traps, each of which makes an interval come out one day off:

1. **Rounding.** Anki rounds halves up. Python's `round()` rounds halves to the nearest even
   number, so `round(32.5)` is 32, and Easy on a 10-day card would come out 32 days instead of
   Anki's 33. Use `math.floor(x + 0.5)`.
2. **Precision.** Anki does this math in 32-bit floats, and Python's floats are 64-bit. In about 1
   case in 300 the extra precision tips a result across a .5: at I = 45 and 130% ease, Good is 58
   days in Anki and 59 in plain Python. Round the ease, the 1.2 and 1.3 multipliers, and every
   intermediate sum and product to 32 bits:

   ```python
   def _f32(x: float) -> float:
       """x at 32-bit float precision, which is what Anki's scheduler computes in."""
       return struct.unpack("f", struct.pack("f", x))[0]
   ```

`ease_factor` itself is an integer, so ease changes are exact and need neither fix.

#### Acceptance examples

Each row is at least one test. `now` is any fixed UTC time.

| Given | When | Then |
| --- | --- | --- |
| a new card | Again / Hard / Good / Easy | learning step 0, due in 1m / learning step 0, due in 5m30s / learning step 1, due in 10m / review, 4 days, ease 2500 |
| a learning card on step 1 | Good | review, `interval_days` 1, due in 1 day, ease 2500 |
| a learning card on step 1 | Again | learning step 0, due in 1m |
| a review card, I = 1, 250%, on time | Hard / Good / Easy | 2 / 3 / 4 days (the minimums decide all three) |
| a review card, I = 10, 250%, on time | Hard / Good / Easy | 12 / 25 / 33 days |
| the same card, 4 days overdue | Hard / Good / Easy | 12 / 30 / 46 days |
| a review card, I = 100, 230%, 7 days overdue | Hard / Good / Easy | 120 / 238 / 320 days |
| a review card, I = 45, 130%, on time | Hard / Good / Easy | 54 / 58 / 76 days (the 32-bit case) |
| a review card, I = 30, 250% | Again | relearning step 0, due in 10m, ease 2300, `lapses` 1, `interval_days` 1 |
| that relearning card | Hard / Good / Easy | relearning, due in 15m / review, due in 1 day / review, 2 days |
| a review card at 130% ease | Again, or Hard | ease stays 1300 |
| a review card at 250% ease | Easy | ease 2650 |
| a review card, I = 20000, 250% | Good | 36500 days |

**Not in this story.** These are deliberate differences from Anki (decisions L1 and L4):

- **Fuzz.** Anki randomly shifts review intervals by a few percent so that cards learned together
  don't keep coming due on the same day. Leaving it out keeps every result predictable in tests.
- **The early-review formula.** It's never needed: story 2 doesn't serve review cards early, and
  story 5 refuses them with a 409.
- Per-deck settings, FSRS, Anki's load balancer, and leech tagging. `lapses` is counted, so leech
  tagging can be added later.
- Saving anything. That's story 5.

**If this is too much for one person,** split it along Anki's own lines: 1a takes new, learning
and relearning cards (the minute-based tables), and 1b takes review cards (the day-based table and
the arithmetic). You'll share one file, so agree on the private helper names first.

**Done when:** every acceptance example is a passing test, and
`python -m pytest --cov=app --cov-report=term-missing` shows `scheduler.py` fully covered.

---

### Story 2 — Due cards

**Owner:** _TBD_ · **Roughly:** 3–4 hours · **After:** Step 0a
**Files:** `backend/app/api/decks.py` (one new route), `backend/tests/test_due_cards.py`

> *As a learner, I want to open a deck and get only the cards due now, so that I'm not
> re-studying cards I just learned.*

- `GET /api/decks/<id>/due`, exactly as in
  [the contract](#get-apidecksiddue--story-2): `@login_required`, `_own_deck_or_404()`, three
  queries, and one `utcnow()` shared by all three.
- The limits and the 20-minute window come from `app/scheduler.py` (`NEW_CARDS_PER_SESSION`,
  `REVIEWS_PER_SESSION`, `LEARN_AHEAD`). Don't retype the numbers.
- Order and limit in SQL, with `.order_by()` and `.limit()`, not by slicing a Python list
  (rule 5).

**Acceptance examples.** Build the cards with `make_card` and set times relative to `utcnow()`.
No clock-freezing library is needed.

| Given | When | Then |
| --- | --- | --- |
| signed out | GET | 401 |
| another user's deck | GET | 404 |
| a deck with no cards | GET | `{"learning": [], "review": [], "new": []}` |
| one card in each state, all due | GET | each card in its list, with `relearning` under `learning` |
| reviews due 3 days ago, yesterday, and tomorrow | GET | `review` is [3 days ago, yesterday] |
| two reviews due at the same moment | GET | the lower `id` comes first |
| learning cards due 1 hour ago, in 5 minutes, and in 30 minutes | GET | `learning` is [1 hour ago, in 5 minutes] |
| 25 new cards | GET | the first 20 created |
| 205 due reviews | GET | the 200 most overdue |
| any response | | every card includes `state` and `due_at` |

**Not in this story** (decisions L4 and L5): per-day limits (until we record review history, a
second session on the same day gets 20 more new cards), Anki's 4 a.m. day boundary, and random
ordering of ties.

**Done when:** the tests pass on both SQLite and Postgres in CI, and `/api/decks/1/due` on the
seeded deck returns its four cards under `new`.

---

### Story 3 — Study session

**Owner:** _TBD_ · **Roughly:** 5–6 hours · **After:** Step 0b
**Files:** `frontend/src/study/session.js`, `frontend/tests/session.test.mjs`

> *As a learner, I want to see one card at a time, reveal the answer, and rate myself, so that I
> review actively.*

A pure reducer for React's `useReducer`. It decides which card is showing. It doesn't compute
intervals (rule 6), render anything, or call the API.

**Exports**

- `initSession({ due, now })`, where `due` is story 2's response and `now` is in milliseconds
  (`Date.now()`). Returns the first state, already showing the first card.
- `sessionReducer(state, action)`, with three actions:
  - `{ type: 'reveal' }`
  - `{ type: 'answered', rating, card, now }`, where `card` is the updated card story 5 returns
  - `{ type: 'skipped', now }`, for when story 5 answers 409: drop the card and move on
- A comment at the top of the file documenting the state's shape. It needs at least the learning
  queue, the main queue, the current card, whether it's revealed, whether the session is
  finished, a count per rating, and when the next learning card is due.

**Rules.** These are Anki's, from its session code in `rslib/src/scheduler/queue/`.

1. The main queue is the `review` list followed by the `new` list. The learning queue is the
   `learning` list, kept sorted by `due_at`.
2. Picking the next card: a learning card that's due now comes first; otherwise the next card in
   the main queue; otherwise a learning card due within `LEARN_AHEAD_MS`; otherwise the session is
   finished.
3. `answered` is ignored until the card has been revealed, and `reveal` is ignored when nothing is
   showing.
4. After `answered`: if `card.state` is `learning` or `relearning`, the card goes back into the
   learning queue by `due_at`. A card in any other state leaves the session.
5. No immediate repeats: if the main queue is empty and the card just answered would be picked
   again straight away, it goes after the next learning card instead, when there is one.
6. When the session finishes, the state holds the counts per rating and the `due_at` of the next
   learning card, if any are left, so the page can say "more cards in 25 minutes".
7. Never mutate `state`; return a new object. The tests freeze the state they pass in, to prove
   it.

**Acceptance examples.** Cards can be minimal objects, like
`{ id: 1, state: 'review', due_at: '2026-10-01T14:00:00Z' }`.

| Given | When | Then |
| --- | --- | --- |
| 1 review card and 2 new cards | start | the review card is showing, not revealed |
| a card showing, not revealed | `answered` good | nothing changes |
| a revealed new card, with other cards left | `answered` good, the card back as learning due in 10m | the next main-queue card shows, and the answered card is in the learning queue |
| a learning card due now, with main-queue cards left | next pick | the learning card shows first |
| main queue empty, learning cards A and B waiting | A `answered` again, due in 1m | B shows next, not A |
| main queue empty, one learning card due in 15m | next pick | it shows (learn ahead) |
| main queue empty, one learning card due in 25m | next pick | finished, with the next due time set to that card's `due_at` |
| a revealed review card | `answered` good, the card back as review | it leaves the session |
| the last card | `answered` | finished, with the right counts |
| a card showing | `skipped` | the next card shows, and the counts don't change |

**Not in this story:** the study page, buttons, keyboard shortcuts, undo, and showing each
button's next interval. Reviews come before new cards; that's Anki's "show after reviews" option,
while its default mixes the two (decision L11).

**Done when:** `npx vitest run tests/session.test.mjs` passes, and CI's eslint step is clean.

---

### Story 4 — Typed answer

**Owner:** _TBD_ · **Roughly:** 3–4 hours · **After:** Step 0b
**Files:** `frontend/src/study/typedAnswer.js`, `frontend/tests/typedAnswer.test.mjs`

> *As a learner, I want to type my answer and have it checked, so that I test real recall instead
> of grading myself.*

Anki's "type in the answer" feature only shows a letter-by-letter comparison and leaves the grading
to you, so there's no Anki rule to copy here. These rules are ours, from the SPPP's "exact or
near-exact matches". The verdict **pre-selects** a rating button, and the learner can still pick a
different one (after typing a valid synonym, say).

**Export:** `checkTypedAnswer(expected, typed)`, returning `{ verdict, suggestedRating }`, where
`verdict` is `'correct'`, `'close'`, or `'incorrect'`.

**Rules, checked in order**

1. Normalize both strings: Unicode NFC, trim, collapse runs of whitespace to one space, lowercase,
   and strip punctuation from both ends. Punctuation in the middle stays.
2. The typed answer is blank → `incorrect`.
3. Equal → `correct`.
4. Equal once accents are removed (NFD, then drop the combining marks) → `close`.
5. The digits in each differ → `incorrect`. Typos in numbers aren't forgiven.
6. Within the typo allowance → `close`. An edit is one inserted, deleted, or replaced character,
   or two neighboring characters swapped (the "optimal string alignment" distance). The allowance
   depends on the length of the normalized expected answer: none for 3 characters or fewer, 1 edit
   for 4 to 7, and 2 edits for 8 or more.
7. Anything else → `incorrect`.

`suggestedRating` uses the values in `RATINGS` from `constants.js`: `correct` → `good`, `close` →
`hard`, `incorrect` → `again`. It never suggests `easy`; that's the learner's call.

**Acceptance examples**

| Expected | Typed | Verdict |
| --- | --- | --- |
| the library | The Library. | correct |
| the library | `  the   library ` | correct |
| adiós | adios | close |
| receive | recieve | close (one swap) |
| la biblioteca | la bibloteca | close |
| mitochondria | mitocondrai | close (two edits) |
| cat | car | incorrect (too short to allow a typo) |
| 1945 | 1946 | incorrect (numbers must match) |
| photosynthesis | respiration | incorrect |
| anything | (blank) | incorrect |

**Not in this story:** Anki's letter-by-letter comparison view, accepting more than one answer
("colour / color"), and AI grading for long answers.

**Done when:** `npx vitest run tests/typedAnswer.test.mjs` passes, and CI's eslint step is clean.

---

### Story 5 — Save a review

**Owner:** _TBD_ · **Roughly:** 3–4 hours · **After:** Step 0a; story 1 for the last two tests
**Files:** `backend/app/api/cards.py` (one new route), `backend/tests/test_review.py`

> *As a learner, I want my rating saved when I answer a card, so that the app remembers when to
> show it to me next.*

- `POST /api/cards/<id>/review`, exactly as in
  [the contract](#post-apicardsidreview--story-5).
- In order: `_own_card_or_404()`, then `json_object()`, then the rating (`Rating(value)` raises
  `ValueError` for anything that isn't one of the four; turn that into the 422), then the due
  check, then `answer_card()`, then commit.
- The due check reads `card.schedule`: a `new` card is always due; a `review` card is due when
  `due_at` ≤ now; a `learning` or `relearning` card is due when `due_at` ≤ now + `LEARN_AHEAD`.
- Import the scheduler by name, `from app.scheduler import LEARN_AHEAD, Rating, answer_card`, so
  tests can swap it out with `monkeypatch.setattr("app.api.cards.answer_card", fake)`.
- One `utcnow()` per request, used for both the due check and `answer_card()`.

**The tests come in two groups,** so this story doesn't have to wait for story 1.

*Group A: the route, with a fake scheduler.* Replace `answer_card` with a fake that returns a
known `CardSchedule`. These tests pass as soon as Step 0a is merged, and they're where your
red/green screenshots come from.

| Given | When | Then |
| --- | --- | --- |
| signed out | POST | 401 |
| no such card, or another user's card | POST | 404, and the other user's card is unchanged |
| a body that isn't JSON | POST | 400 |
| no `rating`, or `"rating": "great"`, or `"rating": 3` | POST | 422 with `field: "rating"` |
| a review card due tomorrow | POST good | 409, and the card is unchanged |
| a learning card due in 30 minutes | POST good | 409 |
| a learning card due in 10 minutes | POST good | 200 (learn ahead) |
| a new card | POST good | 200, and the fake was called with the card's schedule, `Rating.GOOD`, and an aware UTC `now` |
| any 200 | | the response matches what the fake returned, and `GET /api/decks/:id/cards` shows the same `state` and `due_at` afterwards, so it was saved |

*Group B: with the real scheduler.* Add these once story 1 is on `develop`.

| Given | When | Then |
| --- | --- | --- |
| a new card | POST good | `state` is learning, `due_at` is 10 minutes after the request |
| a review card, I = 10, 250%, due now | POST good | `state` is review, `interval_days` is 25 in the database, `due_at` is 25 days out |

For "10 minutes after the request", take `utcnow()` just before and just after the call and check
that `due_at` falls between the two, plus 10 minutes.

If story 1 runs late, merge with group A and add group B in a follow-up PR.

**Done when:** both groups pass, and [the walk-through](#the-walk-through) works.

---

## Lab 3 deliverables

Everyone submits their own report. For your story you need:

1. **Your source code and test code:** the files listed under your story.
2. **How TDD and BDD applied:** your user story, the acceptance examples as Given / When / Then,
   and the red → green → refactor loop you followed. Name the tools: **pytest** for backend
   stories, or **Vitest** for frontend ones (it uses Jest's API, so "a Jest-compatible test
   runner" is accurate if you want to tie it to the handout's list), plus Docker and the commands
   below. BDD here means the Given / When / Then scenarios; we don't use a Cucumber-style tool
   (decision L13).
3. **Screenshots of the tests failing first, then passing.**
4. **A screenshot of the tests passing inside the container.**
5. **An AI usage log table:** tool, task, final use, how you evaluated or changed the output, and
   a summary of the prompt and output.

### The red/green routine

1. Write the tests first. Give the code under test a stub that fails them. A stub that returns its
   input unchanged gives clearer failures than `raise NotImplementedError`: you see assertion diffs
   rather than exceptions.
2. Run the tests. **Screenshot the failures.** Commit: `test(<story>): <what> (red)`.
3. Implement until they pass. Don't edit a test to make it pass unless the test was wrong, and if
   it was, say so in your report. **Screenshot the passing run.** Commit:
   `feat(<story>): <what>`.
4. Refactor with the tests green, and commit.
5. Run your tests in the container. **Screenshot it.**

Keep the red commit; it's your evidence. Merge your PR with **"Create a merge commit"**, not
"Squash and merge", or GitHub folds the red commit away. If your PR is already open when you push
the red commit, CI will go red. That's expected. Just don't merge until it's green.

### Commands

On your machine, run these from `code/backend` or `code/frontend`. Run the container ones from
`code/`, with the stack up (`docker compose up -d`).

| | On your machine | In the container |
| --- | --- | --- |
| Backend, one file | `python -m pytest tests/test_<name>.py -v` | `docker compose exec backend python -m pytest tests/test_<name>.py -v` |
| Frontend, one file | `npx vitest run tests/<name>.test.mjs` | `docker compose exec frontend npx vitest run tests/<name>.test.mjs` |
| Backend, everything | `python -m pytest --cov=app --cov-report=term-missing` | `docker compose exec backend python -m pytest` |
| Frontend, everything | `npm test` | `docker compose exec frontend npm test` |

The coverage flags need `pytest-cov`, which is in `requirements-dev.txt` and isn't installed in the
container. On your machine: `pip install -r requirements.txt -r requirements-dev.txt` for the
backend, and `npm ci` for the frontend.

**Why the Dockerfiles didn't change:** the `dev` targets in `backend/Dockerfile` and
`frontend/Dockerfile` both `COPY . .`, so `tests/` is in the image; `docker-compose.yml`
bind-mounts the source over it, so the container always runs your latest code; `pytest` is in
`requirements.txt`; and Vitest is a dev dependency, which the image's `npm ci` installs.

---

## Schedule

One branch per story, off `develop`: `feat/lab3-0a-backend-foundation`,
`feat/lab3-0b-frontend-foundation`, `feat/lab3-1-scheduler`,
`feat/lab3-2-due-cards`, `feat/lab3-3-session`, `feat/lab3-4-typed-answer`, `feat/lab3-5-review`.
Open a PR into `develop`, get one review, and merge as soon as it's green and reviewed.

The dates are _TBD_ until we pin down the Lab 3 due date.

| When | What should be true |
| --- | --- |
| **Day 0** | Plan agreed, owners named. 🔴 Steps 0a and 0b merged by the end of the day. |
| **Day 1** | Everyone has their red commit and screenshot. |
| **Day 2** | Stories 1–4 green, PRs open. Story 5 group A green. |
| **Day 3** | Story 1 merged, so story 5 adds group B. 🟡 All five merged. |
| **Day 4** | The walk-through works on a fresh database. Container screenshots taken. Reports written. |
| **Lab due** | Submitted. |

### The walk-through

The whole backend path, on the seeded deck, run from `code/`:

```bash
docker compose down -v && docker compose up -d --build
docker compose exec backend flask db upgrade
docker compose exec backend flask seed

curl -s -c /tmp/cadence -H 'Content-Type: application/json' \
  -d '{"email":"demo@cadence.local","password":"demo1234"}' localhost:5001/api/auth/login
curl -s -b /tmp/cadence localhost:5001/api/decks/1/due          # four cards under "new"
curl -s -b /tmp/cadence -H 'Content-Type: application/json' \
  -d '{"rating":"good"}' localhost:5001/api/cards/1/review      # "learning", due in 10 minutes
curl -s -b /tmp/cadence localhost:5001/api/decks/1/due          # card 1 now under "learning"
curl -s -b /tmp/cadence -H 'Content-Type: application/json' \
  -d '{"rating":"good"}' localhost:5001/api/cards/1/review      # "review", due tomorrow
curl -s -b /tmp/cadence -H 'Content-Type: application/json' \
  -d '{"rating":"good"}' localhost:5001/api/cards/1/review      # 409: not due until tomorrow
```

Using `flask db upgrade` instead of `init-db` here also proves the migration builds a working
database from nothing.

### Things that could go wrong

| Risk | What we do about it |
| --- | --- |
| Step 0a or 0b slips | Both are small on purpose, and neither waits on the other. If one isn't merged by the evening of Day 0, someone pairs on it. |
| The frontend container can't find Vitest after 0b | The old `node_modules` volume is still attached. `docker compose up --build -V` |
| Story 1 runs long | It's the biggest story. Split it into 1a and 1b on Day 1 if the red tests show it's more than one person's work. Story 5 doesn't wait: group A uses a fake. |
| A scheduler test disagrees with this plan | The examples were checked against Anki's source. If a case looks wrong, check `rslib/src/scheduler/states/`, then fix the plan in the channel, not just your test. |
| Coverage drops below 90% | Every branch needs a test. Run pytest with `--cov=app --cov-report=term-missing` before opening the PR. |
| "Passes on SQLite, fails on Postgres" | Almost always a datetime with no timezone. Use `card.schedule` or `as_utc()`, and compare in SQL against an aware `utcnow()`. |
| Local database missing the new columns | `docker compose exec backend flask db upgrade` |
| The red commit turns CI red | Expected. Don't merge until it's green. |

---

## Decisions we made

These are numbered L1–L14 so they don't collide with Iteration 1's D1–D7, which all still stand
except two: D1 ("no study mode this iteration") is what this lab starts, and D3 ("no migrations
yet") was replaced by Flask-Migrate — see `doc/CICD.md`.

- **L1 — Anki's default scheduler, default settings, no fuzz.** It's well proven, and it's what
  the SPPP promised. FSRS, Anki's newer optional scheduler, is out. Fuzz is random by design;
  leaving it out makes every result testable, and it can come back later with a random source the
  tests control.
- **L2 — Scheduling state lives on the card row.** Six columns rather than a separate table, the
  same as Anki. A review is one read and one write. A review-history table comes later (L5).
- **L3 — Ease is an integer in thousandths.** Anki stores it that way, and integer arithmetic
  makes ease changes exact.
- **L4 — Due times are exact timestamps.** Anki uses day numbers with a 4 a.m. rollover, so a
  review card is available from the start of its due day. Ours becomes available at the time of
  day it was last answered. Matching Anki needs each user's time zone; revisit if it feels wrong
  in use.
- **L5 — Session limits are per request, not per day.** Anki's 20 new and 200 reviews per day
  need a record of what was studied today. That record is the review-history table, which comes
  after the lab.
- **L6 — The frontend never computes intervals.** One copy of the algorithm, in Python (rule 6).
- **L7 — Reviewing a card that isn't due yet is a 409.** We don't implement Anki's early-review
  formula, so an early answer would be scored as if it were on time and inflate the interval: a
  double-clicked Good on a 10-day card would push it out to 63 days instead of 25. Refusing it is
  simpler than implementing the formula. It reuses `conflict`, so the errors table stays closed.
- **L8 — The migration is in Step 0a, not story 2.** Stories 2 and 5 both need the columns. If
  either one owned them, the other would wait on that whole story.
- **L9 — The new routes go in the existing blueprints.** `/decks/<id>/due` goes in `decks.py` and
  `/cards/<id>/review` in `cards.py`, so `app/api/__init__.py` stays untouched, as the Iteration 1
  plan asked.
- **L10 — Reviewing a card updates its `updated_at`.** `TimestampMixin` bumps it on any change.
  That's fine for now; revisit if the UI starts showing "last edited".
- **L11 — Reviews before new cards.** Anki's default mixes new cards in among reviews; "show after
  reviews" is one of its options. Ours is simpler and deterministic.
- **L12 — Vitest for every frontend test, set up before the lab.** We want component tests for the
  study page. Vitest reuses the Vite config and understands JSX with no extra setup, where Jest
  needs Babel configuration alongside Vite, and it uses Jest's API. Setting it up in Step 0b means
  stories 3 and 4 are written with the runner we'll keep, and the lockfile changes once. The
  SPPP's testing section still says Jest and should be updated to match.
- **L13 — BDD without a BDD tool.** Scenarios are written as Given / When / Then in this plan and
  in each report, and each becomes an ordinary test named after it. No Cucumber or pytest-bdd:
  nothing new to install or learn during the lab.
- **L14 — No browser automation.** End-to-end checks stay manual, as the SPPP planned: a
  walkthrough at the end of each iteration. CI's Docker smoke test still checks that the stack
  starts and migrates.

## Out of scope

Don't spend lab time on any of this: the study page and anything else a user can click; review
history and per-day limits; fuzz; FSRS; per-deck settings; leeches; early review; Anki's day
boundary; showing next intervals on the buttons; the typed-answer comparison view; accepting more
than one answer; automated browser tests (Selenium, Cypress, Playwright); AI card generation;
and duplicate detection. The last two were the other
candidate stories for this lab and move to later in Iteration 2.

---

## After the lab

What turns the five stories into a feature, roughly in order. These become Iteration 2
workstreams.

1. **Study page.** `src/api/study.js` with `createStudyApi(request)`, exposing
   `getDueCards(deckId)` and `reviewCard(cardId, rating)`, built and tested the same way as
   `createDecksApi`. `StudyPage.jsx` at `/decks/:id/study`, driven by `sessionReducer`. A "Study"
   button on `DeckDetailPage`, and the route in `App.jsx`. Disable the rating buttons while a
   review is in flight, and dispatch `skipped` on a 409. Component tests use the Vitest and React
   Testing Library setup from Step 0b.
2. **Typed-answer mode** on the study page, using story 4 to pre-select a button.
3. **A review-history table,** one row per answer. It unlocks per-day limits (L5) and stats.
4. **Next intervals on the buttons** ("<1m", "10m", "1d", "4d"), computed by the backend calling
   `answer_card()` once per rating.
5. **Seed data in every state,** so a demo can show learning and review cards without waiting a
   day.

---

## Working with an AI agent

Like the Iteration 1 plan, this file is written so you can hand it to Claude Code (or similar) and
get work that fits with everyone else's. Start a session in `code/` on your story's branch:

```
Read plans/LAB_3_PLAN.md in the code/ directory, all of it. It builds on
plans/ITERATION_1_PLAN.md -- read that file's "Rules that keep the code consistent"
and "Security basics" sections too.

Implement Story <N>: <title>, from "Stories in detail", test-first. This is for a
TDD lab, so work in this order and stop where it says STOP:

1. Write the tests from my story's acceptance examples, in the test file the plan
   names. Give the production code a stub that fails them (returning its input
   unchanged is best). Run the tests and show me the failing output. STOP -- I'll
   take a screenshot and commit.
2. Implement until the tests pass. Don't change a test to make it pass; if you
   think a test is wrong, stop and tell me why. Run the tests and show me the
   passing output. STOP.
3. Refactor anything that needs it, keeping the tests green. Then run the whole
   suite, plus `ruff check .` for a backend story, and show me the result.

Rules:
- Follow "API contract changes" and "The scheduler interface" exactly. If
  something there looks wrong, stop and tell me instead of changing it -- other
  people are writing code against it.
- Only create or edit the files listed under my story. If you need something
  another story owns, tell me instead of writing it.
- Don't translate Anki's source code. Implement from the rules in this plan.
```

A few things that make this go better:

- **Give it the whole file, not a snippet.** The contract and the file layout are what keep six
  people's code compatible.
- **One story per session.** An agent told to "build study mode" will happily reshape the
  contract to fit whatever it wrote last.
- **Hold it at the STOPs.** The screenshots are graded, and an agent left alone will go straight
  from red to green without pausing.
- **Ask for proof.** "Done when" lines describe something you can actually run. "It should work
  now" isn't that.
- **Read what it wrote before you open the PR.** You're explaining this code in your report, and
  you're reviewing each other's.
- **Log your AI use as you go.** The report needs the table, and it's much easier to fill in
  while you still remember what you asked.
