#!/bin/sh
# Starts the app in one container: migrations, then a worker, then the web server.
# A separate worker service only needs the `taskiq worker` line as its start command.
set -e

alembic upgrade head
taskiq worker app.jobs.broker:broker app.jobs.tasks --workers "${TASKIQ_WORKERS:-1}" \
  --max-async-tasks "${TASKIQ_MAX_ASYNC_TASKS:-20}" &
# exec makes uvicorn PID 1, so it receives the shutdown signal. The app logs each request
# itself, with its ID, so uvicorn's own access log is off.
# uvicorn reads its process count from WEB_CONCURRENCY, which defaults to 1.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --no-access-log
