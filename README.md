# Cadence

An AI-assisted spaced-repetition learning platform. Describe what you want to learn, and Cadence writes the flashcards, then schedules them so you review each one right before you'd forget it.

[![CI](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml/badge.svg)](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml)

Iteration 1 presentation video: [demo/CS673_presentation1_team2.md](demo/CS673_presentation1_team2.md)

## Why

Spaced repetition works, but the tools built around it ask a lot of the learner. Building a deck in Anki means writing every card by hand or hunting down someone else's deck that doesn't quite fit. And the default review format — reveal the answer, grade yourself — suits some material poorly and leaves honest assessment up to you.

Cadence generates cards from a prompt or your own source material, then drills them through several interaction formats with assisted grading. The scheduling model follows Anki's, which is well-proven; the authoring and review experience is where we differ.

It's aimed at people who need to retain a lot of discrete facts: students in medicine, law, and the sciences, language learners, and anyone studying for a certification exam.

## Features

- **Deck management** — create, edit, and delete decks and cards
- **Study mode** — study a deck one card at a time: reveal the answer, then rate it Again, Hard, Good, or Easy, with each button showing when the card would come back
- **Spaced repetition scheduling** — Anki's default algorithm schedules each card's next review, and every deck shows what's due
- **Saved progress** — decks, cards, and each card's schedule are stored in the database and survive refreshes and sign-outs
- **Planned** — AI deck generation (Iteration 3); typed answers and multiple choice if time allows

## Tech Stack

React + Vite · Python + Flask + SQLAlchemy · PostgreSQL · Docker · GitHub Actions · Render

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.12 and Node 22, only to run the tests outside Docker

### Setup

```bash
git clone https://github.com/BUMETCS673/CS673OLF26P2.git
cd CS673OLF26P2/code
cp .env.example .env          # then put a real SECRET_KEY in it
docker compose up --build
```

Once the containers are up, create the tables and add some demo data:

```bash
docker compose exec backend flask db upgrade
docker compose exec backend flask seed     # demo@cadence.local / demo1234
```

- Frontend: http://localhost:3000
- Backend: http://localhost:5001 — `curl localhost:5001/api/health` should return `{"status": "ok"}`

To start over from an empty database: `docker compose down -v`, then the steps above again.

If the browser shows `Failed to resolve import` after you pull, a frontend dependency was added and the container still has the old `node_modules` volume. Rebuild with `docker compose up --build -V` (`-V` recreates that volume).

### Tests

```bash
docker compose exec backend python -m pytest
```

Or outside Docker, from `code/backend` (the tests use SQLite, so no database needed):

```bash
pip install -r requirements.txt
pytest
```

The frontend tests use Vitest:

```bash
docker compose exec frontend npm test
```

## Repository Structure

```
doc/      Project documentation — SPPP, SDD, STD, meeting minutes,
          progress reports, iteration presentations
code/
  plans/      Team implementation plans, one per iteration or lab
  frontend/   React client
  backend/    Python API service
```

## Contributing

Branch from `develop` (`feat/`, `fix/`, `test/`, `ci/`, `chore/`, `doc/`), open a pull request back into `develop`, and merge once CI passes and a teammate has reviewed it. `develop` is released to `main` after validation.

## License

_TBD._ The scheduler was written from Anki's documented rules rather than built on its AGPL-3.0 code, so the choice of license is ours; we haven't picked one yet.

---

<sub>Built for CS673 Software Engineering, Boston University Metropolitan College, Fall 1 2026 — Team 2: Miles (team lead, security), Nurzat (requirements), Duc (config/DevOps, design & implementation), Osasenaga (QA).</sub>
