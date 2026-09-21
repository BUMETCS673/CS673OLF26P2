# syntax=docker/dockerfile:1

# Two targets from one file, so the image CI builds and the image that gets deployed
# share every layer up to the last one.
#
#   dev  -> Flask's reloader, source bind-mounted by docker-compose
#   prod -> gunicorn, non-root, no reloader   (the default; what CD pushes)

FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# So `docker compose exec backend flask init-db` works without repeating --app.
ENV FLASK_APP=wsgi.py \
    PYTHONUNBUFFERED=1

EXPOSE 5000


FROM base AS dev

# --debug reloads the server when you save a file (the source is bind-mounted).
CMD ["flask", "run", "--debug", "--host=0.0.0.0", "--port=5000"]


FROM base AS prod

# Nothing in the container needs to write to the source tree, and a process that can't
# edit its own code is one less thing an exploited dependency can do.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# 2 workers x 4 threads is plenty for a class project and fits a 512 MB free tier.
# --access-logfile - sends request logs to stdout, which is where hosts collect them.
#
# Shell form because hosts (Render, Fly, Cloud Run) assign the port at runtime through
# $PORT and the value has to be expanded then, not at build time. `exec` replaces the
# shell so gunicorn is PID 1 and still receives SIGTERM on shutdown.
ENV PORT=5000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --access-logfile - wsgi:app"]
