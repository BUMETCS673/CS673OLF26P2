"""What the app does, between the HTTP routes and the AI graphs.

Routes in `app.api` parse requests and shape responses. Services hold the logic and the database
work, and raise the errors in `app.services.errors` instead of knowing about HTTP. `app.ai` holds
the graphs, prompts and providers, and knows about neither.
"""
