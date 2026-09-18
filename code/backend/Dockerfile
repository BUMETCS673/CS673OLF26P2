FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# So `docker compose exec backend flask init-db` works without repeating --app.
ENV FLASK_APP=wsgi.py \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# --debug reloads the server when you save a file (the source is bind-mounted).
CMD ["flask", "run", "--debug", "--host=0.0.0.0", "--port=5000"]
