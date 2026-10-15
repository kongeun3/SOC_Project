"""Exercise real SAM2/FEM analysis using local samples and the FastAPI client."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from config import ROOT, REPORT_DIR, UPLOAD_DIR
from api import app


def main():
    client = TestClient(app)
    health = client.get("/").json()
    assert health["sam2"] and health["csv_loader"], health
    results = {"health": health, "analyses": []}
    samples = [
        next((ROOT / "past" / "csv").glob("*.csv")),
        ROOT / "test" / "test.jpg",
    ]
    for sample in samples:
        with sample.open("rb") as source:
            upload = client.post(
                "/upload", files={"file": (sample.name, source)}
            ).json()
        assert Path(upload["path"]).parent == UPLOAD_DIR, upload
        response = client.get(
            "/analyze", params={"mesh_size": 20, "capture_date": "2026-05-08"}
        )
        response.raise_for_status()
        result = response.json()
        assert "error" not in result, result
        assert result["result"]["fem"]["total"] > 0, result
        results["analyses"].append(
            {
                "file": sample.name,
                "mode": result["input_mode"],
                "grade": result["result"]["grade"],
            }
        )
    for name in ("pipeline_result.png", "risk_overlay.png", "donut.png", "gauge.png"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, name
        assert response.content.startswith(b"\x89PNG"), name
    (REPORT_DIR / "runtime_check.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
