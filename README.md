# Cadence

An AI-assisted spaced-repetition learning platform. Describe what you want to learn, and Cadence writes the flashcards, then schedules them so you review each one right before you'd forget it.

[![CI](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml/badge.svg)](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml)

**Live site:** https://cadence-frontend-jufj.onrender.com — it runs on Render's free tier, which sleeps after 15 minutes idle, so the first visit after a quiet spell takes about 30 seconds.

AI card generation uses Google Gemini's free tier, so to use it you must be 18 or over and not in the EEA, Switzerland, or the UK, and you shouldn't upload anything containing personal information. To stay within that tier, the site allows 18 generations a day in total and 10 per account.

Presentation videos: [Iteration 1](demo/CS673_presentation1_team2.md) · [Iteration 2](demo/CS673_presentation2_team2.md)

## Why

Spaced repetition works, but the tools built around it ask a lot of the learner. Building a deck in Anki means writing every card by hand or hunting down someone else's deck that doesn't quite fit. And the default review format — reveal the answer, grade yourself — suits some material poorly and leaves honest assessment up to you.

Cadence generates cards from a prompt or your own source material, then drills them two ways: as classic flashcards, or by having you type the answer and checking it for you. The scheduling model follows Anki's, which is well-proven; the authoring and review experience is where we differ.

It's aimed at people who need to retain a lot of discrete facts: students in medicine, law, and the sciences, language learners, and anyone studying for a certification exam.

## Features

- **Deck management** — create, edit, and delete decks and cards
- **AI card generation** — press Generate with AI on any deck and ask for 1 to 25 cards from a prompt, from an uploaded PDF, TXT, or MD file (up to 4 MB), or, once a deck has 10 cards, with Suggest more content. You review every suggestion, and only the ones you accept join the deck, where they keep an AI-generated label
- **Study mode** — study a deck one card at a time: reveal the answer, then rate it Again, Hard, Good, or Easy, with each button showing when the card would come back
- **Typed answers** — switch the study page to Typed answer at any time to type each answer instead. Cadence says whether it matched (ignoring capitals, extra spaces, and punctuation at either end; spelling and accents count), shows the card's answer, and suggests a rating: Good when right, Again when wrong
- **Spaced repetition scheduling** — Anki's default algorithm schedules each card's next review, and every deck shows what's due
- **Saved progress** — decks, cards, and each card's schedule are stored in the database and survive refreshes and sign-outs

## Tech Stack

React + Vite · Python + Flask + SQLAlchemy · PostgreSQL · Google Gemini · Docker · GitHub Actions · Render

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

AI card generation works without a key: `AI_PROVIDER=fake` in `.env` returns sample cards and never contacts Google. For real cards, set `AI_PROVIDER=gemini`, put your Gemini API key in `GEMINI_API_KEY`, and run `docker compose up -d` to apply it. See [code/Readme.md](code/Readme.md#ai-card-generation).

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
doc/          Project documentation — SPPP, SDD, STD, meeting minutes,
              progress reports, iteration presentations, CI/CD guide
demo/         Demo videos, and links to the presentation videos
code/
  plans/      Team implementation plans, one per iteration or lab
  frontend/   React client
  backend/    Python API service
render.yaml   Render blueprint for the live site
```

## Contributing

Branch from `develop` (`feat/`, `fix/`, `test/`, `ci/`, `chore/`, `doc/`), open a pull request back into `develop`, and merge once CI passes and a teammate has reviewed it. `develop` is released to `main` after validation, through a pull request merged with **Create a merge commit**, not squash, so the two branches keep one history.

## License

_TBD._ The scheduler was written from Anki's documented rules rather than built on its AGPL-3.0 code, so the choice of license is ours; we haven't picked one yet.

---

<sub>Built for CS673 Software Engineering, Boston University Metropolitan College, Fall 1 2026 — Team 2: Miles (team lead, security), Nurzat (requirements), Duc (config/DevOps, design & implementation), Osasenaga (QA).</sub>
