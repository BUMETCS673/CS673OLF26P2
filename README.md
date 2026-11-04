# Cadence

An AI-assisted spaced-repetition learning platform. Describe what you want to learn, and Cadence writes the flashcards, then schedules them so you review each one right before you'd forget it.

[![CI](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml/badge.svg)](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)
![Taskiq](https://img.shields.io/badge/Taskiq-0.13-4B5563)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-vector_search-336791)
![Valkey](https://img.shields.io/badge/Valkey-9-6983FF)
![LangChain](https://img.shields.io/badge/LangChain-1.4-1C3C3C?logo=langchain&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C?logo=langgraph&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-tracing_%26_evals-1C3C3C)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-AI-8E75B2?logo=googlegemini&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI%2FCD-2088FF?logo=githubactions&logoColor=white)
![Render](https://img.shields.io/badge/Render-hosting-46E3B7?logo=render&logoColor=black)

**Live site:** https://cadence-frontend-jufj.onrender.com — it runs on Render's free tier, which sleeps after 15 minutes idle, so the first visit after a quiet spell takes about 30 seconds.

AI card generation uses Google Gemini's free tier, so to use it you must be 18 or over and not in the EEA, Switzerland, or the UK, and you shouldn't upload anything containing personal information. To stay within that tier, the site allows 18 generations a day in total and 10 per account.

Presentation videos: [Iteration 1](demo/CS673_presentation1_team2.md) · [Iteration 2](demo/CS673_presentation2_team2.md)

## Why

Spaced repetition works, but the tools built around it ask a lot of the learner. Building a deck in Anki means writing every card by hand or hunting down someone else's deck that doesn't quite fit. And the default review format — reveal the answer, grade yourself — suits some material poorly and leaves honest assessment up to you.

Cadence generates cards from a prompt or your own source material, then drills them two ways: as classic flashcards, or by having you type the answer and checking it for you. The scheduling model follows Anki's, which is well-proven; the authoring and review experience is where we differ.

It's aimed at people who need to retain a lot of discrete facts: students in medicine, law, and the sciences, language learners, and anyone studying for a certification exam.

## Features

- **Deck management** — create, edit, and delete decks and cards
- **AI card generation** — press Generate with AI on any deck and ask for 1 to 25 cards from a prompt, from an uploaded PDF, TXT, or MD file (up to 50 MB), or, once a deck has 10 cards, with Suggest more content. You review every suggestion, and only the ones you accept join the deck, where they keep an AI-generated label
- **Study mode** — study a deck one card at a time: reveal the answer, then rate it Again, Hard, Good, or Easy, with each button showing when the card would come back
- **Typed answers** — switch the study page to Typed answer at any time to type each answer instead. Cadence says whether it matched (ignoring capitals, extra spaces, and punctuation at either end; spelling and accents count), shows the card's answer, and suggests a rating: Good when right, Again when wrong
- **Spaced repetition scheduling** — Anki's default algorithm schedules each card's next review, and every deck shows what's due
- **Saved progress** — decks, cards, and each card's schedule are stored in the database and survive refreshes and sign-outs
- **Deck tutor** — chat about a deck, ask questions, and practice weak cards. Any card it proposes joins the deck only if you accept it
- **Problem cards** — cards you keep forgetting get a background review that recommends changes for you to accept or reject
- **Shared knowledge base** — card generation can search uploads and accepted cards from all learners, after screening, source limits, and a trust check on accounts. You can report a wrong card to take its sources out of shared search
- **Live job progress** — uploads and generation run as background jobs, and the page follows them as they happen

## Tech Stack

| Area | Tools |
|---|---|
| **Frontend** | React, Vite |
| **Backend** | Python, FastAPI, SQLAlchemy, Alembic |
| **Background jobs** | Taskiq, Valkey |
| **Data** | PostgreSQL with pgvector |
| **AI** | LangChain, LangGraph, Google Gemini |
| **AI tracing and evaluations** | LangSmith |
| **Metrics and logs** | OpenTelemetry, Grafana Cloud (Prometheus, Loki) |
| **Delivery** | Docker, GitHub Actions, Render |

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.12 and Node 22, only to run the tests outside Docker

### Setup

```bash
git clone https://github.com/BUMETCS673/CS673OLF26P2.git
cd CS673OLF26P2/code
cp .env.example .env
docker compose up --build
```

Once the containers are up, create the tables and add some demo data:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli seed     # demo@cadence.local / demo1234
```

- Frontend: http://localhost:3000
- Backend: http://localhost:5001 — `curl localhost:5001/api/health` should return `{"status": "ok"}`

AI card generation works without a key: `AI_WRITER_PROVIDER=fake` in `.env` returns sample cards and never contacts Google. For real cards, set `AI_WRITER_PROVIDER=gemini`, put your Gemini API key in `GEMINI_API_KEY`, and run `docker compose up -d` to apply it. See [code/Readme.md](code/Readme.md#ai-card-generation).

To start over from an empty database: `docker compose down -v`, then the steps above again.

If the browser shows `Failed to resolve import` after you pull, a frontend dependency was added and the container still has the old `node_modules` volume. Rebuild with `docker compose up --build -V` (`-V` recreates that volume).

### Tests

CI runs every test on each pull request. The backend tests need Postgres with pgvector and Valkey, and their tools aren't in the Docker image, so to run them yourself, stop the stack first and start from `code/backend`:

```bash
docker run -d --name cadence-test-db -e POSTGRES_DB=cadence_test -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg18
docker run -d --name cadence-test-valkey -p 6379:6379 valkey/valkey:9
pip install -r requirements.txt -r requirements-dev.txt
REDIS_URL=redis://localhost:6379/0 python -m pytest
```

The frontend tests use Vitest:

```bash
docker compose exec frontend npm test
```

## Observability

### Logs

The API and the worker write one line per event to stdout. On Render that's JSON, which any log tool can read as is. Locally, `LOG_FORMAT=text` in `.env` makes it easier to read in a terminal.

| Setting | Default | Values |
|---|---|---|
| `LOG_FORMAT` | `json` (`text` in Docker Compose) | `json`, `text` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Every JSON line has `time`, `level`, `logger` and `message`, and these fields when they apply:

- **A request's lines** have `request_id`. The ID comes back in the `X-Request-ID` response header. An `X-Request-ID` sent by a proxy is kept if it's a plain ID.
- **When a request ends**, one `request` line from `app.access` adds `method`, `route` (the template, like `/api/decks/{deck_id}`), `status` and `duration_ms`. Health checks log at `DEBUG`, so they don't fill the log.
- **An unhandled error** logs `unhandled error` with its `error_type` and `stack`, the code it ran through.
- **A background job's lines** have `job_id`, `kind` and `attempt`.
- **When an AI call fails**, an `ai call failed` line adds `failure` (such as `rate_limited` or `overloaded`), `vendor_error` and, when there is one, the HTTP `status`.

Logs never include what a learner wrote or uploaded, or an error's message, which can quote it. They hold types, counts and IDs only. Model calls are traced separately in LangSmith when `LANGSMITH_TRACING=true`.

### Metrics and Grafana

With an OpenTelemetry endpoint set, each process also sends its metrics and its log lines over OTLP. Grafana Cloud stores the metrics in Prometheus and the lines in Loki, with each line's fields as attributes. Without an endpoint, nothing is sent.

1. In Grafana Cloud, open **Connections → OpenTelemetry (OTLP)** and create a token.
2. On the backend's Render **Environment** tab, set `OTEL_EXPORTER_OTLP_ENDPOINT` to the endpoint it shows, and `OTEL_EXPORTER_OTLP_HEADERS` to `Authorization=Basic%20<the encoded token>`. Locally, put the same two in `.env`.
3. In Grafana, **Dashboards → New → Import** [doc/grafana/cadence-dashboard.json](doc/grafana/cadence-dashboard.json), and pick your Prometheus and Loki data sources.

| Metric (as named in Prometheus) | Labels | What it counts |
|---|---|---|
| `http_server_request_duration_seconds` | `http_route`, `http_request_method`, `http_response_status_code` | Each API request and how long it took. Health checks aren't measured, and a path no route matched is `unmatched`. |
| `cadence_jobs_total`, `cadence_job_duration_seconds` | `kind`, `outcome` (`done`, `retried`, `failed`) | Each background job attempt, and how long it ran |
| `cadence_ai_calls_total` | `role`, `model`, `outcome` (`ok`, or the failure, like `rate_limited`) | Each model call |
| `cadence_ai_tokens_total` | `role`, `model`, `direction` (`input`, `output`) | Tokens each model used |

Each series also has `job` (`cadence/api` or `cadence/worker`) and `instance`, one per process. On Render, the API's two workers and the job worker share one container, so they report separately. Set `OTEL_RESOURCE_ATTRIBUTES` to tag where they run, as `render.yaml` does with `deployment.environment.name=production`.

## Repository Structure

```
doc/          Project documentation — SPPP, SDD, STD, meeting minutes,
              progress reports, iteration presentations, CI/CD guide,
              and the Grafana dashboard
demo/         Demo videos, and links to the presentation videos
code/
  plans/      Team implementation plans, one per iteration or lab
  frontend/   React client
  backend/    Python API service
render.yaml   Render blueprint for the live site
```

## Contributing

Branch from `develop` (`feat/`, `fix/`, `refactor/`, `test/`, `ci/`, `chore/`, `doc/`), open a pull request back into `develop`, and merge once CI passes and a teammate has reviewed it. `develop` is released to `main` after validation, through a pull request merged with **Create a merge commit**, not squash, so the two branches keep one history.

## License

_TBD._ The scheduler was written from Anki's documented rules rather than built on its AGPL-3.0 code, so the choice of license is ours; we haven't picked one yet.

---

<sub>Built for CS673 Software Engineering, Boston University Metropolitan College, Fall 1 2026 — Team 2: Miles (team lead, security), Nurzat (requirements), Duc (config/DevOps, design & implementation), Osasenaga (QA).</sub>
