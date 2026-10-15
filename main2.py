"""Serve the visually editable HTML dashboard and the existing analysis API."""

import os
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlsplit

sys.dont_write_bytecode = True

import requests
import uvicorn

from config import (
    CLIENT_URL,
    LOG_DIR,
    OLLAMA_AUTO_START,
    OLLAMA_BASE,
    OLLAMA_MODEL,
    ROOT,
    SERVER_HOST,
    SERVER_PORT,
)


def create_app():
    """Serve only web/ as public files; keep the existing API at /api."""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from api import app as analysis_api

    application = FastAPI(
        title="SOC Web", docs_url=None, redoc_url=None, openapi_url=None
    )

    @application.middleware("http")
    async def refresh_design_changes(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.mount("/api", analysis_api)
    application.mount("/", StaticFiles(directory=ROOT / "web", html=True))
    return application


def ollama_models():
    try:
        response = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        response.raise_for_status()
        return [model["name"] for model in response.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return None


class LogStream:
    """Keep model output and server diagnostics in the console and one log file."""

    def __init__(self, console, logfile):
        self.console = console
        self.logfile = logfile

    def write(self, text):
        self.console.write(text)
        self.logfile.write(text)
        self.logfile.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.logfile.flush()

    def isatty(self):
        return False


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    stdout, stderr = sys.stdout, sys.stderr
    ollama_process = None
    with (LOG_DIR / "server2.log").open("a", encoding="utf-8") as logfile:
        sys.stdout = LogStream(stdout, logfile)
        sys.stderr = LogStream(stderr, logfile)
        try:
            print(
                f"\n--- SOC HTML UI | {datetime.now().isoformat(timespec='seconds')} ---"
            )
            print(f"브라우저 주소: {CLIENT_URL}")
            print("모델을 준비합니다. 서버 시작 후 위 주소로 접속하세요. 종료: Ctrl+C")
            models = ollama_models()
            if (
                models is None
                and OLLAMA_AUTO_START
                and urlsplit(OLLAMA_BASE).hostname in ("localhost", "127.0.0.1", "::1")
            ):
                try:
                    ollama_process = subprocess.Popen(
                        ["ollama", "serve"],
                        cwd=ROOT,
                        env=dict(os.environ, OLLAMA_HOST=OLLAMA_BASE),
                        stdout=logfile,
                        stderr=subprocess.STDOUT,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        ),
                    )
                    for _ in range(10):
                        time.sleep(1)
                        models = ollama_models()
                        if models is not None:
                            break
                except FileNotFoundError:
                    print("Ollama를 찾지 못했습니다. AI 진단을 사용하려면 설치하세요.")
            if OLLAMA_MODEL not in (models or []):
                print(f"AI 모델을 확인하세요: ollama pull {OLLAMA_MODEL}")
            uvicorn.run(create_app(), host=SERVER_HOST, port=SERVER_PORT)
        except KeyboardInterrupt:
            pass
        finally:
            if ollama_process is not None and ollama_process.poll() is None:
                ollama_process.terminate()
                try:
                    ollama_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    ollama_process.kill()
                    ollama_process.wait()
            sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    main()
