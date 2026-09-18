"""What Docker runs: `flask --app wsgi run`.

Keeping this separate from the factory means the app is built exactly once, in one
place, whether it's the dev server, the CLI, or a real WSGI server later.
"""

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
