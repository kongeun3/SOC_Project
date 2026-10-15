"""Headless Edge check for main2's editable HTML UI. AI responses are stubbed."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from websockets.sync.client import connect

from config import CLIENT_URL, REPORT_DIR, RESULT_DIR, ROOT


class BrowserPage:
    def __init__(self, url):
        self.ws = connect(url, max_size=32_000_000, open_timeout=10)
        self.counter = 0
        self.responses = {}
        self.errors = []
        self.ai_error = True
        self.chat_requests = []

    def call(self, method, params=None):
        self.counter += 1
        identifier = self.counter
        self.ws.send(
            json.dumps({"id": identifier, "method": method, "params": params or {}})
        )
        while identifier not in self.responses:
            message = json.loads(self.ws.recv(timeout=180))
            if "id" in message:
                self.responses[message["id"]] = message
            elif message.get("method") == "Runtime.exceptionThrown":
                self.errors.append(message["params"])
            elif message.get("method") == "Fetch.requestPaused":
                event = message["params"]
                is_chat = event["request"]["url"].endswith("/api/chat")
                if is_chat:
                    self.chat_requests.append(
                        json.loads(event["request"].get("postData", "{}"))
                    )
                    body = {"reply": "브라우저 연결 점검 응답입니다."}
                    status = 200
                elif self.ai_error:
                    body, status = {"error": "AI 응답 실패 점검"}, 503
                else:
                    body, status = {
                        "diagnosis": "## 연결 점검\n\nAI 응답을 안전하게 표시합니다. <img src=x onerror=alert(1)>"
                    }, 200
                self.call(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": event["requestId"],
                        "responseCode": status,
                        "responseHeaders": [
                            {"name": "Content-Type", "value": "application/json"}
                        ],
                        "body": base64.b64encode(
                            json.dumps(body, ensure_ascii=False).encode()
                        ).decode(),
                    },
                )
        message = self.responses.pop(identifier)
        assert "error" not in message, message
        return message.get("result", {})

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        assert "exceptionDetails" not in result, result
        return result.get("result", {}).get("value")

    def wait(self, expression, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.15)
        raise AssertionError(f"Browser condition timed out: {expression}")

    def screenshot(self, name):
        data = self.call(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )
        (RESULT_DIR / "browser" / name).write_bytes(base64.b64decode(data["data"]))


def main():
    artifact_dir = RESULT_DIR / "browser"
    artifact_dir.mkdir(exist_ok=True)
    profile = artifact_dir / f"edge-profile-{time.time_ns()}"
    downloads = artifact_dir / "downloads"
    downloads.mkdir(exist_ok=True)
    executable = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not executable.exists():
        executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    assert executable.exists(), "Install Edge or Chrome for browser checks"
    response = requests.get(CLIENT_URL + "/", timeout=30)
    response.raise_for_status()
    assert response.headers.get("Cache-Control") == "no-store"
    for private in ("/.env", "/.git/config", "/main.py"):
        assert requests.get(CLIENT_URL + private).status_code == 404, private
    with (artifact_dir / "edge.log").open("a", encoding="utf-8") as log:
        browser = subprocess.Popen(
            [
                str(executable),
                "--headless=new",
                "--remote-debugging-port=0",
                "--no-first-run",
                "--disable-extensions",
                "--disable-sync",
                "--disable-background-networking",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        page = None
        browser_socket = None
        try:
            active_port = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 40
            while not active_port.exists():
                assert time.monotonic() < deadline, "Browser did not start"
                time.sleep(0.2)
            port, browser_path = active_port.read_text().splitlines()[:2]
            browser_socket = connect(
                f"ws://127.0.0.1:{port}{browser_path}", open_timeout=10
            )
            target = requests.put(
                f"http://127.0.0.1:{port}/json/new?about:blank"
            ).json()
            page = BrowserPage(target["webSocketDebuggerUrl"])
            page.call("Runtime.enable")
            page.call("Page.enable")
            page.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1440,
                    "height": 1100,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            page.call(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(downloads)},
            )
            page.call(
                "Fetch.enable",
                {
                    "patterns": [
                        {"urlPattern": "*/api/diagnose"},
                        {"urlPattern": "*/api/chat"},
                    ]
                },
            )
            page.call("Page.navigate", {"url": CLIENT_URL + "/"})
            page.wait(
                "document.querySelector('#connectionStatus')?.dataset.state === 'ready'"
            )
            page.screenshot("html-desktop-empty.png")
            page.evaluate(
                "document.querySelector('#autoDiagnose').checked = false; document.querySelector('#meshSize').value = '30'; document.querySelector('#captureDate').value = '2026-05-08'"
            )
            root = page.call("DOM.getDocument")["root"]["nodeId"]
            node = page.call(
                "DOM.querySelector", {"nodeId": root, "selector": "#fileInput"}
            )["nodeId"]
            page.call(
                "DOM.setFileInputFiles",
                {"nodeId": node, "files": [str(ROOT / "test" / "test.jpg")]},
            )
            page.wait("!document.querySelector('#analyzeButton').disabled")
            assert (
                page.evaluate("document.querySelector('#fileName').textContent")
                == "test.jpg"
            )
            page.evaluate("document.querySelector('#analyzeButton').click()")
            page.wait(
                "!document.querySelector('#downloadButton').disabled && document.querySelector('#operationProgress').hidden",
                timeout=300,
            )
            assert not page.evaluate(
                "!document.querySelector('#errorMessage').hidden"
            ), page.evaluate("document.querySelector('#errorMessage').textContent")
            assert (
                page.evaluate("document.querySelector('#resultMesh').textContent")
                == "30x30"
            )
            page.wait(
                "document.querySelector('#gaugeImage').naturalWidth > 0 && document.querySelector('#donutImage').naturalWidth > 0"
            )
            page.evaluate("document.querySelector('#diagnoseButton').click()")
            page.wait(
                "!document.querySelector('#errorMessage').hidden && !document.querySelector('#diagnoseButton').disabled"
            )
            assert page.evaluate("!document.querySelector('#downloadButton').disabled")
            page.ai_error = False
            page.evaluate("document.querySelector('#diagnoseButton').click()")
            page.wait(
                "!!document.querySelector('#diagnosisContent h4') && !document.querySelector('#diagnoseButton').disabled"
            )
            assert (
                page.evaluate(
                    "document.querySelectorAll('#diagnosisContent img, #diagnosisContent script').length"
                )
                == 0
            )
            page.evaluate(
                "document.querySelector('#chatInput').value = '분석 결과를 알려주세요'; document.querySelector('#chatButton').click()"
            )
            page.wait(
                "document.querySelectorAll('.chat-message').length === 2 && !document.querySelector('#chatButton').disabled"
            )
            assert (
                page.chat_requests
                and page.chat_requests[-1]["message"] == "분석 결과를 알려주세요"
            )
            download_started = time.time()
            page.evaluate("document.querySelector('#downloadButton').click()")
            deadline = time.monotonic() + 15
            while (
                not [
                    p
                    for p in downloads.glob("*.json")
                    if p.stat().st_mtime >= download_started
                ]
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            download = max(
                (
                    p
                    for p in downloads.glob("*.json")
                    if p.stat().st_mtime >= download_started
                ),
                key=lambda p: p.stat().st_mtime,
            )
            assert (
                json.loads(download.read_text(encoding="utf-8"))["mesh_resolution"]
                == "30x30"
            )
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot("html-desktop-result.png")
            page.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
            )
            page.evaluate("window.scrollTo(0, 0)")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            ), "Mobile overflow"
            page.screenshot("html-mobile.png")
            page.call("Page.navigate", {"url": (ROOT / "web" / "index.html").as_uri()})
            page.wait(
                "!!document.querySelector('#previewNotice') && !document.querySelector('#previewNotice').hidden"
            )
            assert page.evaluate("document.querySelector('#analyzeButton').disabled")
            assert not page.errors, page.errors
            report = {
                "server": CLIENT_URL,
                "static_files": "PASS",
                "private_files_not_exposed": "PASS",
                "browser_upload": "PASS",
                "real_image_analysis_30x30": "PASS",
                "ai_error_retry_and_rendering_mocked": "PASS",
                "chat_api_wiring_mocked": "PASS",
                "json_download": "PASS",
                "mobile_layout": "PASS",
                "local_file_designer_preview": "PASS",
                "javascript_exceptions": page.errors,
            }
            (REPORT_DIR / "html_ui_check.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        finally:
            if page:
                page.ws.close()
            if browser_socket is None and (profile / "DevToolsActivePort").exists():
                port, path = (
                    (profile / "DevToolsActivePort").read_text().splitlines()[:2]
                )
                browser_socket = connect(f"ws://127.0.0.1:{port}{path}", open_timeout=3)
            if browser_socket:
                try:
                    browser_socket.send(
                        json.dumps({"id": 1, "method": "Browser.close"})
                    )
                finally:
                    browser_socket.close()
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.terminate()
                browser.wait(timeout=10)


if __name__ == "__main__":
    main()
