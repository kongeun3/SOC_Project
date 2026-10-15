"""Check multi-user isolation and queued work without loading SAM2 or Ollama.

Run with the SOC environment: python -X utf8 test/check_concurrency.py
The HTTP routes, session ownership, job queue and LLM prompt builders are real;
only expensive model inference and the Ollama transport are replaced.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from PIL import Image


def import_backend():
    """Prevent model allocation at import; production loading is unchanged."""
    torch_stub = ModuleType("torch")
    torch_stub.cuda = SimpleNamespace(is_available=lambda: False)
    segmentation_stub = ModuleType("core.segmentation")

    def skip_model(*args, **kwargs):
        raise RuntimeError("SAM2 intentionally skipped by concurrency check")

    segmentation_stub.SAM2PromptTuner = skip_model
    transform_stub = ModuleType("sam2.utils.transforms")
    transform_stub.SAM2Transforms = object
    with patch.dict(sys.modules, {
        "torch": torch_stub,
        "core.segmentation": segmentation_stub,
        "sam2.utils.transforms": transform_stub,
    }):
        return importlib.import_module("api")


class ControlledAnalysis:
    """Hold the worker while real HTTP requests continue in other threads."""

    def __init__(self):
        self.release = threading.Event()
        self.release.set()
        self.entered = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []

    def block(self):
        self.entered.clear()
        self.release.clear()

    def __call__(self, image_path, output_dir, analysis_id, **parameters):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.entered.set()
            if not self.release.wait(20):
                raise TimeoutError("Test did not release the analysis worker")
            marker = Path(image_path).read_text(encoding="utf-8")
            if marker == "fail":
                raise RuntimeError("intentional test failure")
            stress = {"A1": 1.1, "A2": 3.3, "B1": 2.2}[marker]
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            color = {"A1": "red", "A2": "green", "B1": "blue"}[marker]
            (out / "images").mkdir()
            Image.new("RGB", (4, 4), color).save(out / "images" / "gauge.png")
            result = {
                "analysis_id": analysis_id,
                "marker": marker,
                "result": {
                    "grade": "Safe",
                    "fem": {
                        "max_stress_MPa": stress, "max_ratio": stress / 10,
                        "critical": 0, "warning": 0, "safe": 10, "total": 10,
                    },
                    "sam2": {"crack_pixels": 123, "crack_ratio": 0.1},
                },
                "props": {"month": 5, "base_temp": 15, "S_t": 10},
                "verification": {},
                "scenario_info": {"name": "test", "desc": "test"},
                "images": {"gauge.png": f"/analyses/{analysis_id}/images/gauge.png"},
            }
            (out / "analysis.json").write_text(json.dumps(result), encoding="utf-8")
            with self.lock:
                self.calls.append({
                    "marker": marker, "analysis_id": analysis_id,
                    "output_dir": str(out), "parameters": parameters,
                })
            return result
        finally:
            with self.lock:
                self.active -= 1


def new_session(client):
    response = client.post("/session")
    response.raise_for_status()
    return {"X-SOC-Session": response.json()["session_id"]}


def upload(client, headers, marker, filename="same.csv"):
    response = client.post(
        "/upload", headers=headers,
        files={"file": (filename, marker.encode(), "text/csv")},
    )
    response.raise_for_status()
    return response.json()["upload_id"]


def submit(client, headers, endpoint, payload):
    response = client.post(f"/jobs/{endpoint}", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["job_id"]


def job(client, headers, job_id):
    response = client.get(f"/jobs/{job_id}", headers=headers)
    response.raise_for_status()
    return response.json()


def finished(client, headers, job_id, expected="completed"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = job(client, headers, job_id)
        if result["status"] in ("completed", "failed"):
            assert result["status"] == expected, result
            return result
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not finish: {result}")


def image_path(result):
    path = result["images"]["gauge.png"]
    return path.removeprefix("/api")


def run_checks(api, client, work):
    a, b = new_session(client), new_session(client)
    assert a != b
    assert client.post("/upload", files={"file": ("a.csv", b"A1")}).status_code == 401
    assert client.get("/jobs/missing", headers={"X-SOC-Session": "invalid"}).status_code == 401
    assert client.get("/static/gauge.png").status_code == 404
    ua = upload(client, a, "A1")
    ub = upload(client, b, "B1")
    assert ua != ub
    for wrong_id in (ub, uuid4().hex):
        response = client.post("/jobs/analyze", headers=a, json={"upload_id": wrong_id})
        assert response.status_code == 404, response.text

    work.block()
    barrier = threading.Barrier(2)

    def concurrent_submit(headers, upload_id):
        barrier.wait(timeout=5)
        return submit(client, headers, "analyze", {"upload_id": upload_id, "mesh_size": 20})

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(concurrent_submit, a, ua)
        fb = pool.submit(concurrent_submit, b, ub)
        ja, jb = fa.result(timeout=5), fb.result(timeout=5)
    assert work.entered.wait(5), "Worker did not start"
    snapshots = [job(client, a, ja), job(client, b, jb)]
    assert sorted(item["status"] for item in snapshots) == ["queued", "running"], snapshots
    queued = next(item for item in snapshots if item["status"] == "queued")
    assert queued["queue_position"] == 1, queued
    assert client.get(f"/jobs/{ja}", headers=b).status_code == 404
    manager = api.job_manager
    with manager._condition:
        for headers in (a, b):
            manager.sessions[headers["X-SOC-Session"]].last_seen = (
                time.monotonic() - manager.session_ttl - 1
            )
    assert job(client, a, ja)["status"] in ("queued", "running")
    assert job(client, b, jb)["status"] in ("queued", "running")
    started = time.monotonic()
    assert client.get("/").status_code == 200
    assert client.get("/scenarios").status_code == 200
    assert new_session(client)
    ua2 = upload(client, a, "A2", "../../same.csv")
    responsive_seconds = time.monotonic() - started
    assert responsive_seconds < 2, f"HTTP blocked for {responsive_seconds:.2f}s"
    assert not work.release.is_set()
    work.release.set()
    ra = finished(client, a, ja)["result"]
    rb = finished(client, b, jb)["result"]
    assert ra["marker"] == "A1" and rb["marker"] == "B1", (ra, rb)
    assert ra["analysis_id"] != rb["analysis_id"]
    assert image_path(ra) != image_path(rb)
    images = []
    for owner, foreign, result in ((a, b, ra), (b, a, rb)):
        url = image_path(result)
        response = client.get(url, headers=owner)
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"\x89PNG")
        images.append(response.content)
        assert client.get(url, headers=foreign).status_code == 404
        assert client.get(url).status_code == 401
        for endpoint in ("diagnose", "chat"):
            payload = {"analysis_id": result["analysis_id"], "message": "check"}
            assert client.post(f"/jobs/{endpoint}", headers=foreign, json=payload).status_code == 404
    assert images[0] != images[1], "Different users received the same overwritten image"

    newer = submit(client, a, "analyze", {"upload_id": ua2})
    ra2 = finished(client, a, newer)["result"]
    assert ra2["marker"] == "A2" and ra2["analysis_id"] != ra["analysis_id"]
    assert client.get(image_path(ra), headers=a).content == images[0]

    for owner, result, stress, other in ((a, ra, "1.1", "2.2"), (b, rb, "2.2", "1.1")):
        analysis_id = result["analysis_id"]
        diagnosis = submit(client, owner, "diagnose", {"analysis_id": analysis_id})
        chat = submit(client, owner, "chat", {"analysis_id": analysis_id, "message": "결과를 설명해주세요"})
        text = finished(client, owner, diagnosis)["result"]["diagnosis"]
        reply = finished(client, owner, chat)["result"]["reply"]
        assert f"{stress} MPa" in text and f"{other} MPa" not in text, text
        assert f"{stress} MPa" in reply and f"{other} MPa" not in reply, reply
        assert "3.3 MPa" not in text and "3.3 MPa" not in reply
    for endpoint in ("diagnose", "chat"):
        payload = {"analysis_id": uuid4().hex, "message": "check"}
        assert client.post(f"/jobs/{endpoint}", headers=a, json=payload).status_code == 404

    ufail = upload(client, a, "fail")
    failed = submit(client, a, "analyze", {"upload_id": ufail})
    failure = finished(client, a, failed, expected="failed")
    assert failure["error"], failure
    recovery = submit(client, b, "analyze", {"upload_id": ub})
    assert finished(client, b, recovery)["result"]["marker"] == "B1"

    work.block()
    held = submit(client, a, "analyze", {"upload_id": ua})
    assert work.entered.wait(5)
    pending_a = submit(client, a, "diagnose", {"analysis_id": ra["analysis_id"]})
    pending_b = submit(client, b, "chat", {"analysis_id": rb["analysis_id"], "message": "check"})
    assert job(client, a, pending_a)["queue_position"] == 1
    assert job(client, b, pending_b)["queue_position"] == 2
    full = client.post("/jobs/analyze", headers=b, json={"upload_id": ub})
    assert full.status_code == 429, full.text
    work.release.set()
    for headers, job_id in ((a, held), (a, pending_a), (b, pending_b)):
        finished(client, headers, job_id)
    assert work.max_active == 1, f"GPU work overlapped: {work.max_active} workers"
    assert len({call["output_dir"] for call in work.calls}) == len(work.calls)
    assert all(Path(call["output_dir"]).is_dir() for call in work.calls)
    idle = new_session(client)
    idle_upload = upload(client, idle, "A1")
    idle_path = manager.upload_path(idle["X-SOC-Session"], idle_upload)
    with manager._condition:
        manager.sessions[idle["X-SOC-Session"]].last_seen = (
            time.monotonic() - manager.session_ttl - 1
        )
    assert client.get("/jobs/missing", headers=idle).status_code == 401
    assert idle_path.is_file(), "Session expiry must retain saved output"
    return {
        "simultaneous_clients": 2,
        "max_simultaneous_model_jobs": work.max_active,
        "http_response_seconds_while_worker_blocked": round(responsive_seconds, 3),
        "checks": [
            "distinct uploads and immutable job inputs", "FIFO queue positions",
            "responsive HTTP during inference", "session ownership for jobs and images",
            "unique image and report directories", "old analysis remains addressable",
            "diagnosis and chat use requested analysis", "failed job recovery", "queue capacity",
            "analysis, diagnosis and chat share the resource queue",
            "idle expiry preserves files and active jobs cannot expire",
        ],
    }


def main():
    api = import_backend()
    from config import REPORT_DIR

    work = ControlledAnalysis()
    with TemporaryDirectory(prefix="concurrency-", dir=REPORT_DIR) as temporary:
        manager = api.JobManager(Path(temporary), queue_capacity=2, max_pending_per_session=4)
        with ExitStack() as stack:
            stack.enter_context(patch.object(api, "job_manager", manager))
            stack.enter_context(patch.object(api, "run_analysis", work))
            stack.enter_context(patch.object(api, "check_ollama_connection", return_value=True))
            stack.enter_context(patch.object(api, "call_ollama", side_effect=lambda prompt, **kwargs: prompt))
            try:
                with TestClient(api.app) as client:
                    report = run_checks(api, client, work)
            finally:
                work.release.set()
                manager.close(wait=True)
    (REPORT_DIR / "concurrency_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("PASS: concurrent requests stay responsive; queued results, images and LLM context remain isolated.")


if __name__ == "__main__":
    main()
