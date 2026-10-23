"""Local web workspace (FastAPI). Binds to 127.0.0.1 by default."""

from .app import create_app

__all__ = ["create_app"]
