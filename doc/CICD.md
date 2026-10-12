# CI/CD

What runs, when, and what to do when it goes red.

## The pipeline

```
   push to a feature branch
            |
            v
      open a PR ------------> CI ---------> [ci-ok] --- required to merge
                              |
                              +-- Backend lint          ruff check (ruff format advisory)
                              +-- Backend tests sqlite  pytest, coverage >= 90%
                              +-- Backend tests pg      pytest against Postgres 18
                              +-- Migrations            db upgrade, db check, downgrade round-trip
                              +-- Frontend              eslint, npm test, vite build
                              +-- Docker                build prod images, Trivy scan, boot the stack
                              |
                         CodeQL (separate workflow, security + quality)
            |
            v
     merge to develop
            |
            v
          CI  --- passes --->  CD
                                |
                                +-- publish   SHA-tagged images to GHCR
                                +-- deploy    skips with a warning (no staging services)
            |
            v
   merge develop to main
            |
            v
          CI ---> CD ---> Render production, then poll /api/health
```

Three workflows:

| File | Trigger | Purpose |
|---|---|---|
| `.github/workflows/ci.yml` | every PR; pushes to `develop`/`main` | lint, test, build, image and stack checks |
| `.github/workflows/codeql.yml` | pushes/PRs to `develop`/`main`; Mondays 06:00 UTC | static analysis into the Security tab |
| `.github/workflows/cd.yml` | CI completing successfully on `develop`/`main` | publish images, deploy |

CD uses `workflow_run`, not `push`. That is deliberate: a `push` trigger would let CD
start on a commit whose tests were still running or had already failed.

## Environments

| Branch | Environment | Deploys to |
|---|---|---|
| `develop` | `staging` | nothing: the environment is empty, so deploy skips with a warning |
| `main` | `production` | the one set of Render services |

There is one set of Render services, deployed from `main` only.

Images land in GHCR either way, tagged three ways — the commit SHA (what a rollback
pins to), the environment name, and `latest` (only ever `main`).

## Running things locally

Unchanged by any of this. `docker-compose.yml` pins the `dev` build targets, so
`docker compose up` still gives you Flask's reloader and Vite's hot reload.

```sh
cd code
cp .env.example .env
docker compose up --build
```

Backend tests and linters, without Docker:

```sh
cd code/backend
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # in-memory SQLite
ruff check .                # this one is the CI gate
ruff format --diff .        # advisory only -- see "Deliberate omissions"

# The same suite against real Postgres, the way the backend-test-postgres job runs it:
docker compose up -d postgres
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/cadence pytest
```

Frontend:

```sh
cd code/frontend
npm ci
npm test
npm run build
npx eslint .
```

### Database migrations

Schema changes are versioned files under `code/backend/migrations/versions/`, applied with
`flask db upgrade`. This supersedes decision **D3** ("no migrations yet"), which was fine
while nothing was deployed — but `db.create_all()` only creates *missing* tables. It will
not add a column to a table that already exists, so the first schema change after a real
deploy would otherwise mean hand-written SQL against live data.

After changing a model:

```sh
cd code/backend
export FLASK_APP=wsgi.py
flask db migrate -m "add cards.difficulty"   # writes a new migration
# READ the generated file before committing it
flask db upgrade
```

Autogenerate is reliable for added columns, indexes and tables, and **wrong** for renames —
a renamed column looks like a drop plus an add, which silently discards the data. Fix
those by hand.

CI enforces this: the Migrations job applies every migration to an empty Postgres, then
runs `flask db check`, which fails if the resulting schema differs from the models. A model
change without a migration cannot reach `develop`. It also round-trips
`downgrade base` → `upgrade`, so a broken `downgrade()` is caught now rather than when
someone urgently needs it.

`flask init-db` still exists, but only for throwaway local databases — it calls
`create_all()` and then stamps the revision table so a later `upgrade` doesn't try to
recreate everything. For an **existing** database that predates migrations, bring it under
control without recreating it:

```sh
flask db stamp 0001_initial_schema
```

## Deploy targets: one-time Render setup

Nothing below is automated, and the `deploy` job **skips with a warning** rather than
failing until it is done. So the pipeline is green in the meantime.

1. **Create the blueprint.** Sign in at [dashboard.render.com](https://dashboard.render.com)
   with the GitHub account that can see `BUMETCS673/CS673OLF26P2`, then
   **New → Blueprint** and pick the repo. It reads `render.yaml` at the root and proposes
   `cadence-db`, `cadence-backend` and `cadence-frontend`, all on the free tier.

2. **Fill in `API_ORIGIN`.** The blueprint marks it `sync: false`, so Render asks for it.
   Set it to the backend's public address, copied from the backend service's page, with
   nothing after `.onrender.com`: no trailing slash and no path.

   ```
   https://cadence-backend-....onrender.com
   ```

   This is what nginx forwards `/api` to. Don't use the internal
   `http://cadence-backend:5000`: free web services can send private-network traffic but
   can't receive it ([Render docs](https://render.com/docs/private-network)). And don't
   add a trailing slash: when `proxy_pass` has a path, even just `/`, nginx swaps the
   `/api/` prefix for it, so the backend gets `/health` instead of `/api/health`. Either
   mistake means the site loads but every API call fails.

3. **Copy the deploy hooks.** For each of `cadence-backend` and `cadence-frontend`:
   **Settings → Deploy Hook → Copy**. Each is a URL containing a secret key — treat it
   like a password and never paste it into an issue or a commit.

4. **Create the GitHub Environments.** Repo **Settings → Environments → New environment**,
   named exactly `staging` and `production`. In `production` only, add two secrets:

   | Secret | Value |
   |---|---|
   | `RENDER_BACKEND_DEPLOY_HOOK` | the backend hook URL |
   | `RENDER_FRONTEND_DEPLOY_HOOK` | the frontend hook URL |

   and one variable:

   | Variable | Value |
   |---|---|
   | `APP_URL` | the frontend's public URL, e.g. `https://cadence-frontend.onrender.com` |

   `APP_URL` is what the post-deploy health poll checks. Leave it unset and the deploy
   still runs, just unverified.

   Leave `staging` empty. There is one set of Render services, and it's production, so
   `develop`'s deploy job skips with a warning instead of deploying every merge to the
   live site. Only a green merge to `main` deploys.

5. **Set the AI settings.** On `cadence-backend`'s **Environment** tab, set
   `GEMINI_API_KEY` and `GEMINI_MODEL` (`gemini-3.5-flash`). Both are `sync: false`, so
   they are always entered by hand and never stored in the repo. `AI_PROVIDER` comes from
   `render.yaml` as `gemini`. To fall back to sample cards, set
   `AI_PROVIDER=fake`. To switch to `gemini-3.5-flash-lite`, set `GEMINI_MODEL` and raise
   `AI_SITE_DAILY_LIMIT`.

The `production` environment has no required reviewer, so a green merge to `main`
deploys without a second approval.

Doing it twice — separate Render services for staging and production, with the staging
hooks in the `staging` environment — is the fuller setup. One set of services, deployed
from `main` only, is fine for a semester project; say so in the progress report either way.

### Free-tier behaviour worth knowing

- Free web services **sleep after 15 minutes idle**. The first request to a cold
  deployment takes ~30 seconds. That is why CD's health poll allows 10 minutes before
  giving up — it is not a hung deploy.
- Free Postgres instances **expire after 30 days**.
- Migrations run automatically: the backend's `dockerCommand` in `render.yaml` runs
  `flask db upgrade` before starting gunicorn. This is safe only with a single instance. A failed migration means gunicorn
  never starts, so the health check fails and the old version keeps serving. Every wake
  from sleep re-runs the upgrade, which is a no-op once the database is at head.
- Gemini's free tier allows **20 requests a day** for the whole project. The site caps
  itself at 18 (`AI_SITE_DAILY_LIMIT`) and each user at 10, in a rolling 24 hours.

## Branch protection

CI only actually protects anything once merges are blocked on it. `ci-ok` is the single
check to require — job names change whenever the pipeline is restructured, which either
silently un-requires them or wedges the branch, but that name never does.

`main` and `develop` are protected in two places.

The repository ruleset **ruleset-1** (Settings → Rules → Rulesets) applies to both
branches:

- `CI passed`, the `ci-ok` job's display name, is the one required status check. The
  branch doesn't have to be up to date with its base first (`strict` is off).
- A pull request with one approving review. Pushing after an approval dismisses it.
- No force-pushes and no deletion.

Classic branch protection on both branches adds one rule the ruleset doesn't have:
review conversations must be resolved before merging.

Check what's in place:

```sh
gh api repos/BUMETCS673/CS673OLF26P2/rulesets --jq '.[] | "\(.id) \(.name) \(.enforcement)"'
gh api repos/BUMETCS673/CS673OLF26P2/rulesets/<id> --jq '.rules[] | .type'
gh api repos/BUMETCS673/CS673OLF26P2/branches/develop/protection \
  --jq '{reviews: .required_pull_request_reviews.required_approving_review_count, conversations: .required_conversation_resolution.enabled}'
```

## When CI goes red

| Job | Likely cause | Fix |
|---|---|---|
| Backend lint | ruff found a style or import-order problem | `cd code/backend && ruff check --fix .` |
| Backend tests (sqlite) | a genuine test failure | reproduce with `pytest` |
| Backend tests (postgres) | SQLite tolerated something Postgres doesn't — a dialect-specific type, or a query relying on SQLite's loose typing | reproduce with the `TEST_DATABASE_URL` command above |
| Backend tests, "Required test coverage not reached" | new code arrived without tests | add tests, or argue the threshold down in `ci.yml` |
| Frontend, eslint | most often `react-hooks/exhaustive-deps` — an effect reading a value it doesn't list | add the dependency; don't silence the rule |
| Frontend, build | a bad import path or broken JSX | `npm run build` locally |
| Docker, "Build backend/frontend image" | the Dockerfile itself broke | `docker build --target prod code/backend` |
| Docker, "Start the stack" | a container exited during boot | read the "Container logs" step, which only appears on failure |
| Docker, "Backend answers /api/health" | Flask is up but erroring, usually the database connection | same logs step |
| Docker, "Scan backend/frontend image" | Trivy found a fixable HIGH/CRITICAL CVE in a base image or dependency | bump the base image tag or the dependency; unfixable ones are already ignored |
| **Migrations, "flask db check"** | a model changed without a matching migration | `cd code/backend && FLASK_APP=wsgi.py flask db migrate -m "what changed"`, read the generated file, commit it |
| Migrations, "downgrade to base and back up" | a migration's `downgrade()` is wrong or incomplete | fix `downgrade()` in the migration file |
| Docker and both backend test jobs fail together, with `toomanyrequests` or 429 in the log | Docker Hub's anonymous pull limit | re-run the failed jobs |
| CD, deploy skipped | expected on `develop`, whose `staging` environment is empty; on `main`, the Render hooks aren't set | on `main`, the setup section above — this is a warning, not a failure |
| CD, health poll timed out | Render build failed, or a cold start took over 10 minutes | Render dashboard → the service → Events |

## Rolling back

Images are tagged by SHA, so a rollback is a redeploy of a known-good commit rather than
a revert-and-wait:

```sh
# What's currently published
gh api /orgs/BUMETCS673/packages/container/cs673olf26p2%2Fbackend/versions \
  --jq '.[0:5] | .[] | .metadata.container.tags'
```

Then either redeploy that commit from the Render dashboard (**Deploys → Redeploy** on the
last good one), or revert the merge on `develop` and let the pipeline run forward. Prefer
the revert if the bad commit is going to confuse anyone looking at history.

## Deliberate omissions

Worth being able to defend in the progress report:

- **No end-to-end browser tests.** The Docker job proves the stack boots and the API
  answers, but nothing drives the UI. Playwright covering signup → create deck → add card
  is the next thing worth adding.
- **Action versions pinned to major tags** (`actions/checkout@v7`), not SHAs. Dependabot
  tracks the majors. SHA pinning is the stricter supply-chain posture and costs little if
  the team wants it.
- **`ruff format` is advisory, not a gate.** It would rewrite many of the backend's
  files, all cosmetic, and it collapses the aligned end-of-line comments used throughout
  (see the `parametrize` lists in `tests/test_auth.py`). `ruff check` — the half that
  finds actual problems — *is* blocking. To make formatting blocking: run `ruff format .`
  once, land it as its own commit so it never mixes with a behaviour change, then drop
  `continue-on-error` from that step. Start of an iteration, not the middle.
- **No load or performance testing.** Out of scope for the free tier.