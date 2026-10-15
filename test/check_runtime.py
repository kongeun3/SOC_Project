"""Exercise real SAM2/FEM analysis using local samples and the FastAPI client."""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from config import ROOT, REPORT_DIR
from api import app, job_manager


def wait_for_result(client, job_id, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] == "completed":
            return job["result"]
        if job["status"] == "failed":
            raise AssertionError(job)
        time.sleep(0.1)
    raise AssertionError(f"Analysis timed out: {job_id}")


def main():
    try:
        with TestClient(app) as client:
            health = client.get("/").json()
            assert health["sam2"] and health["csv_loader"], health
            session = client.post("/session")
            session.raise_for_status()
            client.headers["X-SOC-Session"] = session.json()["session_id"]
            results = {"health": health, "analyses": []}
            samples = [
                next((ROOT / "past" / "csv").glob("*.csv")),
                ROOT / "test" / "test.jpg",
            ]
            for sample in samples:
                with sample.open("rb") as source:
                    response = client.post(
                        "/upload", files={"file": (sample.name, source)}
                    )
                response.raise_for_status()
                upload = response.json()
                response = client.post(
                    "/jobs/analyze", json={
                        "upload_id": upload["upload_id"],
                        "mesh_size": 20, "capture_date": "2026-05-08",
                    }
                )
                response.raise_for_status()
                result = wait_for_result(client, response.json()["job_id"])
                assert result["result"]["fem"]["total"] > 0, result
                for name in ("pipeline_result.png", "risk_overlay.png", "donut.png", "gauge.png"):
                    response = client.get(result["images"][name].removeprefix("/api"))
                    assert response.status_code == 200, name
                    assert response.content.startswith(b"\x89PNG"), name
                results["analyses"].append(
                    {
                        "file": sample.name,
                        "analysis_id": result["analysis_id"],
                        "mode": result["input_mode"],
                        "grade": result["result"]["grade"],
                    }
                )
    finally:
        job_manager.close(wait=True)
    (REPORT_DIR / "runtime_check.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
