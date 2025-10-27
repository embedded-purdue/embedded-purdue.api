# api/index.py - Main FastAPI application entry point
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

# Load environment variables (support .env.local and .env)
# .env.local is preferred for developer machines; .env for general defaults.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env.local"), override=False)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)

# Import route handlers (after env vars are loaded so sub-apps read them)
from app.events import app as events_app
from app.health import app as health_app
from app.media import app as media_app

# Create main app
app = FastAPI(
    title="Embedded Purdue API",
    description="API for managing events and media for Embedded Systems club",
    version="1.0.0",
)

# Configure CORS
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
origins = [ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers from sub-apps
for route in events_app.routes:
    app.routes.append(route)

for route in health_app.routes:
    app.routes.append(route)

for route in media_app.routes:
    app.routes.append(route)

# Root endpoint
@app.get("/")
async def root():
    return {
        "name": "Embedded Purdue API",
        "version": "1.0.0",
        "endpoints": {
            "events": "/api/events",
            "media": "/api/media",
            "health": "/api/health",
        }
    }

@app.get("/api")
async def api_root():
    return {
        "endpoints": {
            "events": {
                "list": "GET /api/events",
                "create": "POST /api/events",
            },
            "media": {
                "list": "GET /api/media",
                "create": "POST /api/media",
                "upload": "POST /api/media/upload",
                "upload_gh": "POST /api/media/upload-gh",
            },
            "health": "GET /api/health",
        }
    }
