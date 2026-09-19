# Cadence — Iteration 1 Plan

**Dates:** Thu 2026-09-17 → Mon 2026-09-21
**Team:** Miles, Von, Nurzat, Duc

## What we're building

Three things, and nothing else:

1. **Log in** — create an account, log in, log out, stay logged in while you use the app.
2. **Decks** — create, rename, and delete your own decks.
3. **Cards** — add, edit, and delete cards inside a deck.

At the end of the weekend, a person should be able to sign up, make a deck, put cards in it, edit
one of them, log out, log back in, and find everything still there.

Study mode, scheduling, and AI card generation are **not** in this iteration. See
[Out of scope](#out-of-scope).

## Contents

- [Who's doing what](#whos-doing-what)
- [Where the code is today](#where-the-code-is-today)
- [Architecture](#architecture)
- [Database tables](#database-tables)
- [API contract](#api-contract)
- [Security basics](#security-basics)
- [Workstreams in detail](#workstreams-in-detail)
- [Schedule](#schedule)
- [Decisions we made](#decisions-we-made)
- [Out of scope](#out-of-scope)
- [Working with an AI agent](#working-with-an-ai-agent)

---

## Who's doing what

Four workstreams, split by frontend/backend and by auth/decks-and-cards.

| # | Workstream | Owner | Depends on |
| --- | --- | --- | --- |
| **0** | **Shared foundation** — project skeleton, all three database tables, dev setup | Miles and Duc, tonight | nothing |
| **1** | **Backend: auth** — register, login, logout, "who am I" | Miles | WS0 |
| **2** | **Backend: decks & cards** — all deck and card endpoints | Von | WS0 |
| **3** | **Frontend: auth** — signup page, login page, logout, route protection | Duc | WS0 |
| **4** | **Frontend: decks & cards** — deck list, deck page, card editor | Nurzat | WS0 |

WS0 is small on purpose and has to land **Thursday night**, because the other four all build on it.

The two halves meet at the [API contract](#api-contract). Frontend and backend owners for the same
feature should read that section together before writing code, and neither side should change it
alone once we start.

---

## Where the code is today

`code/` currently holds a working Docker setup and almost nothing else:

| File | What's there |
| --- | --- |
| `backend/app.py` | A Flask app with one route that returns `"Hello, World!"` |
| `backend/requirements.txt` | Flask, Flask-SQLAlchemy, psycopg2 — installed but not used yet |
| `frontend/src/main.jsx` | A React page that renders `<h1>Cadence</h1>` |
| `docker-compose.yml` | Postgres + backend (port 5001) + frontend (port 3000). This works. |

Three problems WS0 fixes:

- **The backend never connects to the database.** Docker passes in `DATABASE_URL` and the code
  ignores it.
- **The frontend can't call the backend.** The page is served from port 3000 and the API is on port
  5001. Browsers block that by default (it's called CORS). We fix it with a Vite proxy — see
  [decision D4](#decisions-we-made).
- **There's no `.env.example`,** even though the README tells you to copy it.

One thing that looks wrong but isn't: `docker-compose.yml` mounts the Postgres data at
`/var/lib/postgresql`, not `.../data`. That's correct for `postgres:18`. Leave it alone.

---

## Architecture

### File layout at the end of the weekend

```
code/
  docker-compose.yml
  .env.example
  backend/
    Dockerfile
    requirements.txt
    wsgi.py                  # what Docker runs
    app/
      __init__.py            # create_app() — builds and returns the Flask app
      config.py              # reads settings from environment variables
      extensions.py          # db = SQLAlchemy(), login_manager
      models/
        base.py              # shared timestamp columns + the JSON date format
        user.py              # User
        deck.py              # Deck
        card.py              # Card
      api/
        __init__.py          # blueprint registered at /api
        auth.py              # WS1
        decks.py             # WS2
        cards.py             # WS2
      errors.py              # turns errors into consistent JSON
      seed.py                # `flask seed` — demo user + demo deck
    tests/
      conftest.py
      test_foundation.py     # WS0
      test_auth.py           # WS1
      test_decks.py          # WS2
      test_cards.py          # WS2
  frontend/
    vite.config.js           # + proxy so /api reaches the backend
    src/
      main.jsx
      App.jsx                # routes
      api/
        client.js            # one place that does fetch()
        auth.js              # WS3
        decks.js             # WS4
      auth/
        AuthContext.jsx      # WS3 — holds the logged-in user
        ProtectedRoute.jsx   # WS3 — redirects to /login if signed out
      pages/
        LoginPage.jsx        # WS3
        SignupPage.jsx       # WS3
        DeckListPage.jsx     # WS4
        DeckDetailPage.jsx   # WS4
      components/
        DeckForm.jsx         # WS4
        CardForm.jsx         # WS4
        CardRow.jsx          # WS4
```

Each file belongs to exactly one workstream. If you need a file someone else owns, message them
instead of editing it — that's where merge conflicts come from.

### Shared files

Five files can't belong to one workstream, so they're the places two branches will collide. WS0
sets each of them up so nobody has to edit them later:

| File | Why it's shared | Rule |
| --- | --- | --- |
| `backend/app/api/__init__.py` | both backend lanes register a blueprint here | WS0 registers all three up front against empty modules — after that, nobody touches it |
| `backend/app/errors.py` | both backend lanes raise from it and read bodies with its `json_object()` | WS0 owns it. Need a new helper or error code there? Channel first — it's the contract in code |
| `backend/requirements.txt` | either backend lane might add a package | WS0 adds everything we know we need. Anything later goes in the channel first |
| `frontend/src/App.jsx` | WS3 owns routing, but WS4's pages need routes | WS3 adds **all five** routes, with WS4's pointing at placeholder components Nurzat then fills in |
| `frontend/package.json` + `package-lock.json` | new frontend packages | WS3 only. Nurzat shouldn't need a new dependency this iteration |

There's no `package-lock.json` committed today, which means `npm install` can resolve different
versions on each of our machines. WS0 commits one so we're all running the same thing.

### How a request flows

```
Browser (localhost:3000)
  │  fetch("/api/decks")        ← relative URL, so the browser sees one origin
  ▼
Vite dev server ── proxies /api ──▶ Flask (port 5000 inside Docker)
                                      │
                                      ├─ api/decks.py   reads the request, sends back JSON
                                      ├─ models/        SQLAlchemy objects
                                      └─ Postgres
```

### Rules that keep the code consistent

1. **Routes stay thin.** A route reads the request, checks the input, does the database work, and
   returns JSON. Keep the queries in the route rather than scattering them across helper files.
2. **The frontend never writes a URL inline.** Every `fetch` goes through `src/api/client.js` — one
   place to fix when something changes, one place that handles errors.
3. **A test has to exercise the thing it names.** If a fixture prepares the value you then assert
   on, you're testing the fixture — it'll pass just as happily when the real code stops working.
   Build the object the way real code does, and check what the code under test actually produced.
4. **Read request bodies with `json_object()`,** from `app/errors.py` — never `request.get_json()`
   directly. The bare call answers a request with no JSON `Content-Type` with a 415, which isn't in
   the [errors table](#errors). `json_object()` gives you a dict or raises the contract's 400.
5. **Don't count rows in Python.** `len(deck.cards)` looks free and isn't: it loads every card of
   every deck to take a length. Counting belongs in the query — `card_count` on `Deck` is a SQL
   count, so `GET /api/decks` stays one query whether you own three decks or three hundred.

---

## Database tables

Three tables. SQLAlchemy models create them; we're not writing SQL by hand.

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer, primary key | |
| `email` | text, unique, not null | stored lowercase — the model normalizes on assignment |
| `password_hash` | text, not null | **never the actual password** — see [Security](#security-basics) |
| `display_name` | text | optional |
| `created_at` | timestamp, defaults to now | |

The `User` model lowercases and trims `email` whenever it's set, so the row is lowercase no matter
who wrote it — that's what makes the unique constraint mean "one account". It does **not** apply to
reads: normalize user input yourself before looking someone up.

```python
User.query.filter_by(email=User.normalize_email(typed_in))   # finds Miles@BU.edu
User.query.filter_by(email=typed_in)                         # doesn't
```

### `decks`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer, primary key | |
| `user_id` | integer, not null, references `users(id)` | who owns this deck |
| `name` | text, not null | 1–120 characters |
| `description` | text | optional |
| `created_at` / `updated_at` | timestamp | |

### `cards`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer, primary key | |
| `deck_id` | integer, not null, references `decks(id)`, delete cascade | |
| `front` | text, not null | the question |
| `back` | text, not null | the answer |
| `created_at` / `updated_at` | timestamp | |

"Delete cascade" means deleting a deck deletes its cards automatically — the database handles it,
we don't write code for it.

Scheduling columns (due date, interval, ease) get added in Iteration 2 when we build study mode.

### Creating the tables

Two commands, added in WS0:

- `flask init-db` — creates the tables
- `flask seed` — adds a demo user (`demo@cadence.local` / `demo1234`) with one deck and a few cards

To start over: `docker compose down -v`, then `up`, then those two commands again.

---

## API contract

**This is the part that makes four people's work fit together.** Agree on it before writing code.
If something here turns out to be wrong, say so in the team channel and we change it together —
don't change it quietly on your branch.

Everything lives under `/api` and speaks JSON.

### Errors

Every error comes back in the same shape, so the frontend only has to handle one thing:

```json
{ "error": { "code": "not_found", "message": "Deck not found" } }
```

| Status | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` | body isn't valid JSON, or wasn't sent as JSON |
| 401 | `unauthorized` | not logged in, or wrong email/password |
| 403 | `forbidden` | reserved; we answer 404 instead — see [Security](#security-basics) item 3 |
| 404 | `not_found` | the thing doesn't exist, **or isn't yours** |
| 405 | `method_not_allowed` | right URL, wrong HTTP method |
| 409 | `conflict` | email already registered |
| 422 | `validation_error` | a field is missing, blank, or too long |
| 500 | `internal_error` | we crashed; the response never says more than that |

**This table is closed.** Every error the API returns uses one of these codes, so the frontend can
switch on `error.code` and know it has covered everything. If you need a code that isn't here, it
goes in the channel first — adding one is a contract change, and Duc and Nurzat have to handle it.

Sending a body without a `Content-Type: application/json` header is a `400`, not a 415. Flask
raises 415 for it, which is why request bodies get read with `json_object()`
([rule 4](#rules-that-keep-the-code-consistent)) rather than `request.get_json()`.

A body over 1MB is also a `400`, not a 413 — see [D7](#decisions-we-made). Both live in
`REMAPPED_STATUS` in `app/errors.py`, which is where anything like them goes.

### Auth endpoints (WS1 and WS3)

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | `{email, password, display_name?}` | 201, `User` + logs you in |
| `POST` | `/api/auth/login` | `{email, password}` | 200, `User` + sets session cookie |
| `POST` | `/api/auth/logout` | — | 204 |
| `GET` | `/api/auth/me` | — | 200 `User`, or 401 if signed out |

`GET /api/auth/me` is how the frontend knows on page load whether someone is still logged in.

### Deck endpoints (WS2 and WS4)

All require login. All only ever return **your own** decks.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/decks` | — | 200, list of `Deck` |
| `POST` | `/api/decks` | `{name, description?}` | 201, `Deck` |
| `GET` | `/api/decks/:id` | — | 200, `Deck` |
| `PATCH` | `/api/decks/:id` | `{name?, description?}` | 200, `Deck` |
| `DELETE` | `/api/decks/:id` | — | 204 |

### Card endpoints (WS2 and WS4)

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/decks/:id/cards` | — | 200, list of `Card` |
| `POST` | `/api/decks/:id/cards` | `{front, back}` | 201, `Card` |
| `PATCH` | `/api/cards/:id` | `{front?, back?}` | 200, `Card` |
| `DELETE` | `/api/cards/:id` | — | 204 |

### What the objects look like

```jsonc
// User — note there is no password field, ever
{
  "id": 1,
  "email": "demo@cadence.local",
  "display_name": "Demo User",
  "created_at": "2026-09-17T14:00:00Z"
}

// Deck
{
  "id": 3,
  "name": "Spanish 101",
  "description": "Core vocabulary",
  "card_count": 12,
  "created_at": "2026-09-17T14:00:00Z",
  "updated_at": "2026-09-17T14:00:00Z"
}

// Card
{
  "id": 9,
  "deck_id": 3,
  "front": "la biblioteca",
  "back": "the library",
  "created_at": "2026-09-17T14:00:00Z",
  "updated_at": "2026-09-17T14:00:00Z"
}
```

### Validation rules

Both sides check these. The frontend checks so the user gets a fast, friendly message; the backend
checks because **the frontend can be bypassed** and is never the real defense.

| Field | Rule |
| --- | --- |
| `email` | must contain `@`, max 255 characters, stored lowercase |
| `password` | at least 8 characters |
| `name` (deck) | not blank, max 120 characters |
| `description` | optional, max 1000 characters |
| `front` / `back` | not blank, max 2000 characters |

---

## Security basics

Five things. They're all small, and they're the ones a grader is actually going to look for.

### 1. Never store passwords

Hash them. Werkzeug ships with Flask, so there's nothing extra to install:

```python
from werkzeug.security import generate_password_hash, check_password_hash

user.password_hash = generate_password_hash(password)   # on register
check_password_hash(user.password_hash, attempt)        # on login -> True/False
```

The plain password exists only for the moment the request is being handled. It's never stored,
never logged, and never returned in an API response.

### 2. Never build SQL out of strings

This is SQL injection, and it's why we use SQLAlchemy:

```python
# NO — someone types a "name" that ends the string and adds their own SQL
db.session.execute(f"SELECT * FROM decks WHERE name = '{name}'")

# YES — SQLAlchemy sends the value separately from the query
Deck.query.filter_by(name=name).all()
```

**Rule for this iteration: no raw SQL anywhere.** If you think you need it, ask first.

### 3. Always filter by the logged-in user

This is the single most common security bug in student projects. Getting the deck by ID alone lets
anyone read anyone's deck just by changing the number in the URL:

```python
# NO — returns someone else's deck
deck = Deck.query.get_or_404(deck_id)

# YES — only finds it if it's yours
deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first_or_404()
```

Every deck and card query does this. For cards, check ownership by joining through the deck.

Note it returns **404, not 403**. Saying "forbidden" tells an attacker the deck exists. 404 tells
them nothing.

### 4. Sessions in a cookie the browser won't hand over

We use Flask-Login, which stores the session in a signed cookie. Configure it in `config.py`:

- `SESSION_COOKIE_HTTPONLY = True` — JavaScript can't read the cookie, so a script injected into
  the page can't steal the session
- `SESSION_COOKIE_SAMESITE = "Lax"` — other websites can't make requests as you
- `SECRET_KEY` read from the environment, never typed into a file we commit

Protected routes use `@login_required`. Put it on every deck and card endpoint.

### 5. Don't leak information in error messages

Login failures always say the same thing, whether the email doesn't exist or the password is wrong:

> Invalid email or password.

Two different messages would let someone check which emails have accounts.

Also: `.env` stays out of git (it's already in `.gitignore`), `.env.example` holds the variable
names with fake values, and no API keys or passwords go in the repo.

---

## Workstreams in detail

### WS0 — Shared foundation 🔴 blocks everything

**Owners:** Miles and Duc · **Due:** Thursday night · **Roughly:** 3 hours

- `create_app()` factory in `app/__init__.py`; `extensions.py` holding `db` and `login_manager`
- `config.py` reading `DATABASE_URL` and `SECRET_KEY` from the environment
- **All three models** (`User`, `Deck`, `Card`) exactly as in
  [Database tables](#database-tables) — Von needs `Deck` and `Card` ready to use
- `flask init-db` and `flask seed` commands
- `errors.py` producing the JSON error shape above
- `GET /api/health` returning `{"status": "ok"}` so everyone can confirm their setup works
- `app/api/__init__.py` registering **all three** blueprints (`auth`, `decks`, `cards`) against
  empty module files, so WS1 and WS2 never edit the same file — see [Shared files](#shared-files)
- `wsgi.py`, and update `backend/Dockerfile` to run it with `--debug` so code changes reload
- `code/.env.example`
- Vite proxy in `vite.config.js`: `/api` → `http://backend:5000`
- Add to `requirements.txt`: `Flask-Login`, `python-dotenv`
- Run `npm install` in `frontend/` and **commit `package-lock.json`**

**Done when:** from a clean `docker compose down -v`, running `up --build` then `init-db` then
`seed`, and `curl localhost:5001/api/health` returns ok. Post in the channel when it's merged.

---

### WS1 — Backend: auth

**Owner:** Miles · **Roughly:** 4 hours · **After:** WS0

- `app/api/auth.py` — the four endpoints in [the contract](#auth-endpoints-ws1-and-ws3)
- Password hashing and session cookies per [Security](#security-basics) items 1, 4, and 5
- Email stored lowercase and trimmed, so `Miles@BU.edu` and `miles@bu.edu` are the same account
- Registering an email that already exists → 409, not a 500 crash
- `@login_required` available for Von to use on deck and card routes — **tell Von as soon as this
  is on `develop`**
- `tests/test_auth.py`: register works; duplicate email → 409; login with a wrong password → 401;
  `/me` while signed out → 401; `/me` after login returns the user; logout then `/me` → 401

**Done when:** you can register, log in, call `/api/auth/me`, and log out entirely with `curl -c`
and `-b` for cookies.

---

### WS2 — Backend: decks & cards

**Owner:** Von · **Roughly:** 5 hours · **After:** WS0

- `app/api/decks.py` and `app/api/cards.py` — the nine endpoints in the contract
- `@login_required` on every one, and **every query filtered by `current_user.id`**
  ([Security](#security-basics) item 3)
- Validation per the rules table; blank or missing fields → 422 naming the field
- `card_count` included on deck responses — it's already on `Deck`, counted in SQL. Use it; don't
  recompute it with `len(deck.cards)` (rule 5)
- Request bodies read with `json_object()` from `app/errors.py`, not `request.get_json()` (rule 4)
- Deleting a deck deletes its cards (via the cascade, not a loop in Python)
- `tests/test_decks.py` and `tests/test_cards.py`: create/read/update/delete for both; signed out →
  401; **and one test where user A tries to fetch user B's deck and gets 404** — that's the
  important one

**If WS1 isn't merged yet,** don't sit and wait. Write the routes with a temporary
`current_user_id = 1` and a `# TODO: WS1` comment, then swap it for `current_user.id` when auth
lands.

**Done when:** you can create a deck, add cards, edit a card, and delete the deck with `curl`, and
a second user can't see any of it.

---

### WS3 — Frontend: auth

**Owner:** Duc · **Roughly:** 5 hours · **After:** WS0

- Add `react-router-dom`
- `src/api/client.js` — the shared fetch wrapper. Sets JSON headers, sends
  `credentials: "include"` so the session cookie travels, and turns error responses into a thrown
  error carrying `code` and `message`. **Nurzat uses this too**, so build it early and tell them
  when it's pushed.
- `src/api/auth.js` — one function per auth endpoint
- `AuthContext.jsx` — holds the current user, calls `/api/auth/me` once on page load, and exposes
  `login`, `logout`, `register`
- `ProtectedRoute.jsx` — sends signed-out visitors to `/login`
- `LoginPage.jsx` and `SignupPage.jsx` — email and password fields, inline validation, a visible
  error when the server says no, and a disabled button while the request is in flight
- A header showing who's logged in with a logout button
- **All five routes** in `App.jsx`: `/login` and `/signup` public, `/decks` and `/decks/:id`
  protected, plus a redirect from `/`. Point the two deck routes at placeholder components so
  Nurzat can fill them in without either of you editing `App.jsx` twice —
  see [Shared files](#shared-files).

**Don't wait for WS1.** Build against a temporary `src/api/mock.js` that returns a fake user, then
switch to the real calls. The [contract](#api-contract) tells you the exact shapes.

**Done when:** you can sign up, land on the deck list, refresh the page and stay logged in, log
out, and get bounced to `/login` when you try to go back.

---

### WS4 — Frontend: decks & cards

**Owner:** Nurzat · **Roughly:** 5 hours · **After:** WS0, and WS3's `client.js`

- `src/api/decks.js` — functions for all nine deck and card endpoints
- `DeckListPage.jsx` — your decks with names and card counts, a "New deck" form, rename, and delete
  with a confirmation step
- `DeckDetailPage.jsx` — deck name and description, the card list, and an "Add card" form
- `CardForm.jsx` — front and back text areas, used for both creating and editing
- `CardRow.jsx` — shows a card, with edit and delete buttons; editing happens in place
- **Loading and error states on every page**, plus an empty state for "no decks yet". A blank
  screen while data loads is the thing that makes a demo look broken.
- Plain CSS. Readable and consistent beats fancy, and no component library.

**Don't wait for WS2.** Use mock data shaped like the contract and switch over when the real
endpoints land.

**Done when:** logged in, you can create a deck, open it, add two cards, edit one, delete the
other, and see all of it survive a page refresh.

---

## Schedule

We work on branches off `develop`: `feat/ws1-backend-auth`, `feat/ws4-frontend-decks`, and so on.
Open a pull request into `develop`. **Merge as soon as a PR is reviewed** — don't save everything
for Sunday night.

| When | What should be true |
| --- | --- |
| **Thu night** | 🔴 WS0 merged. Everyone can run the app and hit `/api/health`. |
| **Fri end of day** | Backend auth endpoints working via curl. Deck endpoints started. Both frontend lanes have routing and pages rendering against mock data. |
| **Sat end of day** | Backend done for both lanes. Frontend auth switched from mocks to the real API. |
| **Sun midday** | 🟡 Everything connected: sign up → create deck → add cards → edit → refresh → still there. |
| **Sun end of day** | Bugs found and fixed. README updated with real setup steps. |
| **Mon** | `develop` → `main`. Demo practiced. Submitted. |

**Practice the demo Monday morning:** `docker compose down -v` → `up --build` → `init-db` →
`seed` → open localhost:3000 → sign up as a new user → create a deck → add two cards → edit one →
log out → log back in → everything's still there.

### Things that could go wrong

| Risk | What we do about it |
| --- | --- |
| WS0 slips past Thursday | It's deliberately small. If it's shaky by 9pm, someone pairs on it — nobody else can really start until it's done. |
| Frontend stuck waiting on backend | Both frontend lanes start against mock data shaped like the contract. |
| The two halves don't fit together | That's what the [API contract](#api-contract) is for. Read it before you code, and don't change it alone. |
| Everyone merges Sunday night at once | Merge continuously. A reviewed PR doesn't wait. |
| Someone's Docker gets into a weird state | `docker compose down -v`, then `up`, then `init-db` and `seed`. |

---

## Decisions we made

- **D1 — No study mode or scheduling this iteration.** Those need decks and cards to exist first,
  which is what this weekend builds. Iteration 2.
- **D2 — Session cookies, not JWT.** Flask-Login handles it, the cookie is `httpOnly` so page
  scripts can't read it, and there's no token storage to get wrong. JWTs are the thing students
  most often implement insecurely.
- **D3 — No database migrations yet.** `flask init-db` plus `docker compose down -v` to reset.
  Migrations are worth setting up in Iteration 2, once we have data we care about keeping.
- **D4 — Vite proxy instead of CORS configuration.** The browser sees a single origin, so cookies
  just work and there's no CORS setup to get wrong.
- **D5 — We write our own code rather than building on Anki.** Anki is AGPL-licensed, which would
  cover our project too. Writing our own keeps the license our choice. We'll add an MIT `LICENSE`
  file Monday.
- **D6 — A missing `Content-Type` is a 400, not a 415.** Flask raises 415 when a request body
  arrives without `Content-Type: application/json`. Rather than add a sixth error code the frontend
  would have to handle, we read bodies with `json_object()` and the error handler turns any stray
  415 into the contract's 400. Keeps the [errors table](#errors) closed.
- **D7 — Request bodies are capped at 1MB, and 413 is a 400 too.** Without a cap anyone
  can make the server buffer an arbitrarily large body. `MAX_CONTENT_LENGTH` sets the
  limit; Werkzeug then raises 413, which the handler remaps the same way as 415. 1MB is
  deliberately generous — a card is 2000 characters a side, so a legitimate oversized
  paste still gets the 422 naming the field rather than a blunt "too large".

## Out of scope

Don't spend Saturday on any of this: study mode, any scheduling algorithm, AI card generation,
password reset, email verification, "remember me", OAuth or social login, sharing decks between
users, deck folders or tags, import/export, search, mobile-specific layout, and deploying anywhere
other than local Docker.

---

## Working with an AI agent

This file is written so you can hand it to Claude Code (or similar) and get work that fits with
everyone else's. Start a session in `code/` on your own branch:

```
Read ITERATION_1_PLAN.md in the code/ directory, all of it.

Implement Workstream WS<N>: <title>, from the "Workstreams in detail" section.

Rules:
- Follow the "Database tables" and "API contract" sections exactly. If you think something
  there is wrong, stop and tell me instead of changing it — three other people are writing
  code against it.
- Follow the "Security basics" section. In particular: no raw SQL, and every deck and card
  query filtered by the logged-in user.
- Write the tests listed under my workstream. They're part of the work, not a follow-up.
- Only create files listed under my workstream in the file layout. If you need something
  another workstream owns, write a minimal stub with a TODO naming that workstream.

Stop when the "Done when" line for my workstream passes, and show me the command output that
proves it.
```

A few things that make this go better:

- **Give it the whole file, not a snippet.** The contract and the file layout are what keep four
  people's code compatible.
- **One workstream per session.** An agent told to "build the backend" will happily reshape the API
  to match whatever it wrote last.
- **Nobody starts until WS0 is merged.** Every other workstream assumes those files exist.
- **Ask for proof.** "Done when" lines describe something you can actually run. "It should work
  now" isn't that.
- **Read what it wrote before you open the PR.** You're presenting this work, and you're reviewing
  each other's.
