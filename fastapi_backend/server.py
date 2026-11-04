"""Single-container Foodoo deployment: API and built React under one origin."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app import app

# The production image ships a Vite build into /app/dist. In local
# development Vite continues to serve the UI separately on port 5173.
static_root = Path(__file__).resolve().parent / "dist"
if static_root.is_dir():
    # Register LAST so /api/... and /healthz keep their FastAPI handlers.
    app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")
