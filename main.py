"""Run the SOC dashboard and analysis API on the address configured in .env."""

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
    FLET_SECRET_KEY,
    LOG_DIR,
    OLLAMA_AUTO_START,
    OLLAMA_BASE,
    OLLAMA_MODEL,
    ROOT,
    SERVER_HOST,
    SERVER_PORT,
    WEB_UPLOAD_DIR,
)


def create_app():
    """UI at /, analysis API at /api; a single server owns both lifecycles."""
    import flet_web.fastapi as flet_web
    from api import app as analysis_api
    from app import main as dashboard

    application = flet_web.FastAPI(
        title="SOC", docs_url=None, redoc_url=None, openapi_url=None
    )
    application.mount("/api", analysis_api)
    application.mount(
        "/",
        flet_web.app(
            dashboard,
            upload_dir=str(WEB_UPLOAD_DIR),
            secret_key=FLET_SECRET_KEY,
            app_name="SOC · 도로 포장 열응력 진단",
            app_short_name="SOC",
        ),
    )
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
    with (LOG_DIR / "server.log").open("a", encoding="utf-8") as logfile:
        sys.stdout = LogStream(stdout, logfile)
        sys.stderr = LogStream(stderr, logfile)
        try:
            print(f"\n--- SOC | {datetime.now().isoformat(timespec='seconds')} ---")
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
