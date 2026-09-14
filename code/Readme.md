# Cadence

## Running the Application

From the `code` directory, start the application with:

```bash
docker compose up --build
```

The frontend is available at:

http://localhost:3000

The backend is available at:

http://localhost:5001

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
