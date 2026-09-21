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
                                +-- deploy    Render staging, then poll /api/health
            |
            v
   merge develop to main
            |
            v
          CI ---> CD ---> Render production
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
| `develop` | `staging` | Render staging services |
| `main` | `production` | Render production services |

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

# The same suite against real Postgres, the way CI's second matrix leg runs it:
docker compose up -d postgres
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/cadence pytest
```

Frontend:

```sh
cd code/frontend
npm ci
npm run build
npx eslint .                # needs the lint tooling installed, see below
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

### A note on the eslint dependencies

`eslint.config.mjs` imports plugins that are **not** in `package.json`. CI installs them
with `npm install --no-save`, because adding them properly would require regenerating
`package-lock.json`, and `npm ci` — used by CI and by the frontend Dockerfile — fails
when `package.json` and the lockfile disagree.

To lint locally, or to fix this properly:

```sh
cd code/frontend
npm install --save-dev eslint@9.39.0 @eslint/js@9.39.0 globals@16.5.0 \
  eslint-plugin-react@7.37.5 eslint-plugin-react-hooks@7.1.0 \
  eslint-plugin-react-refresh@0.4.24
```

Commit the updated `package.json` **and** `package-lock.json`, then delete the
"Install lint tooling" step from `ci.yml`.

## Deploy targets: one-time Render setup

Nothing below is automated, and the `deploy` job **skips with a warning** rather than
failing until it is done. So the pipeline is green in the meantime.

1. **Create the blueprint.** Sign in at [dashboard.render.com](https://dashboard.render.com)
   with the GitHub account that can see `BUMETCS673/CS673OLF26P2`, then
   **New → Blueprint** and pick the repo. It reads `render.yaml` at the root and proposes
   `cadence-db`, `cadence-backend` and `cadence-frontend`, all on the free tier.

2. **Fill in `API_ORIGIN`.** The blueprint marks it `sync: false`, so Render asks for it.
   Set it to the backend's internal address:

   ```
   http://cadence-backend:5000
   ```

   This is what nginx forwards `/api` to. Getting it wrong means the site loads but every
   API call 502s.

3. **Copy the deploy hooks.** For each of `cadence-backend` and `cadence-frontend`:
   **Settings → Deploy Hook → Copy**. Each is a URL containing a secret key — treat it
   like a password and never paste it into an issue or a commit.

4. **Create the GitHub Environments.** Repo **Settings → Environments → New environment**,
   named exactly `staging` and `production`. In each, add two secrets:

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

5. **Gate production.** On the `production` environment, add a **required reviewer**, so
   a deploy to main waits for a human. Recommended for the final iteration.

Doing it twice — separate Render services for staging and production — is the fuller
setup. A single set of services pointed at by both environments is fine for a semester
project; say so in the progress report either way.

### Free-tier behaviour worth knowing

- Free web services **sleep after 15 minutes idle**. The first request to a cold
  deployment takes ~30 seconds. That is why CD's health poll allows 10 minutes before
  giving up — it is not a hung deploy.
- Free Postgres instances **expire after 30 days**. Diarise it; when it happens, create a
  new one and update `DATABASE_URL`. Do not let this bite during the final demo.
- Migrations run automatically. `preDeployCommand: flask db upgrade` in `render.yaml`
  applies them after the image builds and before traffic moves to the new version — a
  failed migration leaves the old version serving rather than breaking the site. No manual
  Render shell step.

## Branch protection

CI only actually protects anything once merges are blocked on it. `ci-ok` is the single
check to require — matrix leg names change whenever the matrix changes, which silently
un-requires them, but that name never does.

Run these once, with a repo admin's `gh` login:

```sh
for branch in develop main; do
  gh api --method PUT \
    "repos/BUMETCS673/CS673OLF26P2/branches/$branch/protection" \
    --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["CI passed"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
done
```

What each setting buys:

- `"contexts": ["CI passed"]` — the `ci-ok` job's display name. Merges wait for it.
- `strict: true` — the branch must be up to date with its base first. Catches the case
  where two PRs pass separately and break once combined.
- `required_approving_review_count: 1` — someone other than the author reads it.
- `dismiss_stale_reviews` — pushing after an approval re-requests review.
- `enforce_admins: false` — leaves an escape hatch for a genuinely stuck merge. Set it to
  `true` if the team would rather not have one.
- `allow_force_pushes: false` / `allow_deletions: false` — history on the shared branches
  stays intact.

Check it took:

```sh
gh api repos/BUMETCS673/CS673OLF26P2/branches/develop/protection \
  --jq '{checks: .required_status_checks.contexts, reviews: .required_pull_request_reviews.required_approving_review_count}'
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
| CD, deploy skipped | Render hooks not set | the setup section above — this is a warning, not a failure |
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
- **Action versions pinned to major tags** (`actions/checkout@v4`), not SHAs. Dependabot
  tracks the majors. SHA pinning is the stricter supply-chain posture and costs little if
  the team wants it.
- **`ruff format` is advisory, not a gate.** It would rewrite 11 of the backend's 20
  files, all cosmetic, and it collapses the aligned end-of-line comments used throughout
  (see the `parametrize` lists in `tests/test_auth.py`). `ruff check` — the half that
  finds actual problems — *is* blocking. To make formatting blocking: run `ruff format .`
  once, land it as its own commit so it never mixes with a behaviour change, then drop
  `continue-on-error` from that step. Start of an iteration, not the middle.
- **No load or performance testing.** Out of scope for the free tier.
