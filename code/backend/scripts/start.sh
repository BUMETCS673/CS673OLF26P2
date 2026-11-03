#!/bin/sh
# Starts the app in one container: migrations, then a worker, then the web server.
# A separate worker service only needs the `taskiq worker` line as its start command.
set -e

alembic upgrade head
taskiq worker app.jobs.broker:broker app.jobs.tasks --workers 1 --max-async-tasks 20 &
# exec makes uvicorn PID 1, so it receives the shutdown signal.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers 2
