"""Shared local paths and service settings for the SOC application."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", encoding="utf-8-sig")

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
_server = urlsplit(SERVER_URL)
if (
    _server.scheme != "http"
    or not _server.hostname
    or _server.path
    or _server.query
    or _server.fragment
    or _server.username
):
    raise ValueError(
        ".env SERVER_URL must be an HTTP address, e.g. http://127.0.0.1:8000"
    )
SERVER_HOST = _server.hostname
SERVER_PORT = _server.port or 80
if not 1 <= SERVER_PORT <= 65535:
    raise ValueError(".env SERVER_URL port must be between 1 and 65535")
CLIENT_URL = SERVER_URL
if SERVER_HOST in ("0.0.0.0", "::"):
    CLIENT_URL = f"http://127.0.0.1:{SERVER_PORT}"
API_URL = CLIENT_URL + "/api"
WEBSOCKET_URL = CLIENT_URL.replace("http://", "ws://", 1) + "/ws"
FLET_SECRET_KEY = os.environ.get("FLET_SECRET_KEY", "")
if not FLET_SECRET_KEY:
    raise ValueError("Set FLET_SECRET_KEY in the project .env file")

RESULT_DIR = ROOT / "result"
JOBS_DIR = RESULT_DIR / "jobs"
STATIC_DIR = RESULT_DIR / "images"
UPLOAD_DIR = RESULT_DIR / "uploads"
WEB_UPLOAD_DIR = RESULT_DIR / "web_uploads"
REPORT_DIR = RESULT_DIR / "reports"
LOG_DIR = RESULT_DIR / "logs"
WEIGHTS_DIR = ROOT / "weights"
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "exaone3.5:7.8b")
OLLAMA_AUTO_START = os.environ.get("OLLAMA_AUTO_START", "true").lower() in (
    "1",
    "true",
    "yes",
)


def _positive_int(name, default):
    value = int(os.environ.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


# One resource worker owns SAM2, Matplotlib and Ollama. HTTP requests stay concurrent.
JOB_QUEUE_CAPACITY = _positive_int("JOB_QUEUE_CAPACITY", 32)
SESSION_TTL_SECONDS = _positive_int("SESSION_TTL_SECONDS", 86400)
MAX_SESSIONS = _positive_int("MAX_SESSIONS", 256)
MAX_JOBS_PER_SESSION = _positive_int("MAX_JOBS_PER_SESSION", 128)
MAX_UPLOADS_PER_SESSION = _positive_int("MAX_UPLOADS_PER_SESSION", 64)
MAX_PENDING_PER_SESSION = _positive_int("MAX_PENDING_PER_SESSION", 4)
MAX_UPLOAD_MB = _positive_int("MAX_UPLOAD_MB", 32)

for directory in (STATIC_DIR, UPLOAD_DIR, WEB_UPLOAD_DIR, REPORT_DIR, LOG_DIR, JOBS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
