# Cadence

## Running the Application

From the `code` directory, create your environment file and start the application:

```bash
cp .env.example .env
docker compose up --build
```

`.env` is gitignored and never committed. `.env.example` lists every variable with a
placeholder value, so add any new variable to both.

- Frontend: http://localhost:3000
- Backend: http://localhost:5001

## Setting Up the Database

The schema is managed by migrations (Alembic). Run them on a new database, and
again whenever you pull a change that adds one:

```bash
docker compose exec backend alembic upgrade head     # create or update the tables
docker compose exec backend python -m app.cli seed   # demo@cadence.local / demo1234
```


To start over from an empty database:

```bash
docker compose down -v
docker compose up --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli seed
```

## AI Card Generation

`AI_WRITER_PROVIDER` in `.env` chooses what writes the cards, and `AI_JUDGE_PROVIDER` chooses
what checks them:

- `fake`, the value in `.env.example`: a stand-in that returns sample cards without
  contacting Google. No key needed.
- `gemini`: Google's model named in `AI_WRITER_MODEL` (`gemini-3.5-flash-lite` by default) or
  `AI_JUDGE_MODEL` (`gemini-3.8-flash` by default). It needs `GEMINI_API_KEY`.

To try the real model, make your own free key at [Google AI Studio](https://aistudio.google.com)
in a project of its own, so your testing doesn't spend the team's quota, and never set up
billing on it. Put the key in `.env` only.

`.env` is read when a container is created, so after changing it run
`docker compose up -d`. `docker compose restart` keeps the old values.

To check the provider works, generate a few cards in the app. With `gemini`, that spends some of
the free tier's requests for the day. Over a rolling 24 hours, generations are capped by `AI_DAILY_LIMIT` per user (10), and each model's calls across all features
by `AI_MODEL_DAILY_LIMITS` (`model:limit,model:limit`), or `AI_MODEL_DAILY_LIMIT` (18) for unlisted
models. The defaults come from third-party figures, so confirm your real limits in AI Studio.

## Checking It Works

```bash
curl localhost:5001/api/health     # {"status": "ok"} straight from the backend
curl localhost:3000/api/health     # the same, through the Vite proxy
```

The second one is worth checking too: the frontend reaches the backend through a
`/api` proxy in `vite.config.js`, so the browser only ever sees one origin and the
session cookie works without any CORS setup.

## Running the Tests

CI runs every test on each pull request. The tests use stand-in AI with no key, so they don't
call Google or spend its quota. They need Postgres with pgvector and Valkey, and their tools
aren't in the Docker image, so to run them yourself, stop the stack first and start from
`code/backend`:

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

or, outside Docker, `npm ci` and then `npm test` from `code/frontend`.

## Accessing the Frontend Container

The frontend container uses an Alpine-based Node image. Alpine includes `sh` by default instead of `bash`.

To open a shell inside the running frontend container:

```bash
docker compose exec frontend sh
```

Once inside the container, you can run commands such as:

```sh
ls
npm --version
```

Use `exit` to leave the container shell:

```sh
exit
```

## Stopping the Application

To stop the containers:

```bash
docker compose down
```

To stop the containers and remove the database volume:

```bash
docker compose down -v
```

> **Warning:** `docker compose down -v` removes the PostgreSQL volume and any data stored in it.
