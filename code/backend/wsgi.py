"""What Docker runs: `flask --app wsgi run`.

Keeping this separate from the factory means the app is built exactly once, in one
place, whether it's the dev server, the CLI, or a real WSGI server later.
"""

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    # Debug (and its in-browser debugger) only when asked for, never by default.
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
