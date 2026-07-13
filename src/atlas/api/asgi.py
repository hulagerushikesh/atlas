"""
ASGI entry point for uvicorn and docker-compose.

    uvicorn atlas.api.asgi:app --reload

Separated from app.py so that importing atlas.api.app (which happens in tests)
does not trigger create_app() and therefore does not require OPENAI_API_KEY at
import time.
"""

from atlas.api.app import create_app

app = create_app()
