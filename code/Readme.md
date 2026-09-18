# Cadence

## Running the Application

From the `code` directory, create your environment file and start the application:

```bash
cp .env.example .env          # then put a real SECRET_KEY in it
docker compose up --build
```

`.env` is gitignored and never committed. `.env.example` lists every variable with a
placeholder value, so add any new variable to both.

- Frontend: http://localhost:3000
- Backend: http://localhost:5001

## Setting Up the Database

There are no migrations this iteration (decision D3). The tables are created by a
command, and you reset by deleting the volume.

```bash
docker compose exec backend flask init-db   # create users, decks, cards
docker compose exec backend flask seed      # demo@cadence.local / demo1234
```

To start over from an empty database:

```bash
docker compose down -v
docker compose up --build
docker compose exec backend flask init-db
docker compose exec backend flask seed
```

## Checking It Works

```bash
curl localhost:5001/api/health     # {"status": "ok"} straight from Flask
curl localhost:3000/api/health     # the same, through the Vite proxy
```

The second one is worth checking too: the frontend reaches the backend through a
`/api` proxy in `vite.config.js`, so the browser only ever sees one origin and the
session cookie works without any CORS setup.

## Running the Tests

```bash
docker compose exec backend python -m pytest
```

The tests run against in-memory SQLite, so they also work outside Docker from
`code/backend`:

```bash
pip install -r requirements.txt
pytest
```

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
