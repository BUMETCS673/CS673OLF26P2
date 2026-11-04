# syntax=docker/dockerfile:1

# Two targets from one file, so the image CI builds and the image that gets deployed
# share every layer up to the last one.
#
#   dev  -> uvicorn's reloader, source bind-mounted by docker-compose
#   prod -> uvicorn, non-root, no reloader   (the default; what CD pushes)

FROM python:3.12-slim AS base

# Base image tags are rebuilt on their own schedule, so a pinned tag drifts behind the
# distro's security updates -- Trivy found 39 HIGH/CRITICAL in the frontend base this way.
# Upgrading the OS packages here keeps the tag pinned (reproducible) while still picking up
# patches, instead of chasing tag bumps every week.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 5000


FROM base AS dev

# The compose worker's --reload needs this. The prod image has no reloader, so it stays out.
RUN pip install --no-cache-dir "taskiq[reload]==0.13.0"

# --reload restarts the server when you save a file (the source is bind-mounted).
CMD ["uvicorn", "app.main:app", "--reload", "--no-access-log", "--host", "0.0.0.0", "--port", "5000"]


FROM base AS prod

# Nothing in the container needs to write to the source tree, and a process that can't
# edit its own code is one less thing an exploited dependency can do.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Migrations run first, because Render's pre-deploy command is paid-only. A failed upgrade
# means nothing starts, so the previous deploy keeps serving.
ENV PORT=5000
CMD ["scripts/start.sh"]
