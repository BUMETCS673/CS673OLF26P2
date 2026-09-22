# Cadence

An AI-assisted spaced-repetition learning platform. Describe what you want to learn, and Cadence writes the flashcards, then schedules them so you review each one right before you'd forget it.

[![CI](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml/badge.svg)](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml)

Iteration 1 presentation video: [demo/CS673_presentation1_team2.md](demo/CS673_presentation1_team2.md)

## Why

Spaced repetition works, but the tools built around it ask a lot of the learner. Building a deck in Anki means writing every card by hand or hunting down someone else's deck that doesn't quite fit. And the default review format — reveal the answer, grade yourself — suits some material poorly and leaves honest assessment up to you.

Cadence generates cards from a prompt or your own source material, then drills them through several interaction formats with assisted grading. The scheduling model follows Anki's, which is well-proven; the authoring and review experience is where we differ.

It's aimed at people who need to retain a lot of discrete facts: students in medicine, law, and the sciences, language learners, and anyone studying for a certification exam.

## Features

- **AI deck generation** — supply a topic prompt or source material and review the cards the model proposes, accepting, editing, or discarding each one
- **Deck management** — create, organize, edit, and delete decks and cards at any time
- **Spaced repetition scheduling** — per-card performance tracking that schedules each review at the interval where reinforcement is most valuable
- **Multiple review formats** — reveal-and-grade recall, free-text entry, and multiple choice
- **Persistent history** — decks, cards, and study progress survive across sessions

## Tech Stack

React + Vite · Python + Flask + SQLAlchemy · PostgreSQL · Docker · GitHub Actions · Render

## Getting Started

### Prerequisites

- Docker and Docker Compose
- _Node and Python versions TBD_

### Setup

```bash
git clone https://github.com/BUMETCS673/CS673OLF26P2.git
cd CS673OLF26P2/code
cp .env.example .env          # then put a real SECRET_KEY in it
docker compose up --build
```

Once the containers are up, create the tables and add some demo data:

```bash
docker compose exec backend flask init-db
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

## Repository Structure

```
docs/     Project documentation — SPPP, SDD, STD, meeting minutes,
          progress reports, iteration presentations
code/
  frontend/   React client
  backend/    Python API service
```

## Contributing

Branch from `develop` (`feat/`, `fix/`, `chore/`, `doc/`), open a pull request back into `develop`, and merge once CI passes and a teammate has reviewed it. `develop` is released to `main` after validation.

## License

_TBD._ If we build on Anki's codebase, its AGPL-3.0 terms apply to our work; if we implement scheduling independently, we're free to choose. Decision to be made in Iteration 1 design.

---

<sub>Built for CS673 Software Engineering, Boston University Metropolitan College, Fall 1 2026 — Team 2: Miles (team lead), Nurzat (requirements), Paul (frontend), Victor (backend), Duc (config/DevOps), Osasenaga (QA).</sub>
