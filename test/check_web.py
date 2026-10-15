"""Check a running web UI, including its real analysis button event."""

import asyncio
import argparse
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import msgpack
import requests
import websockets
from config import ROOT, REPORT_DIR, CLIENT_URL, API_URL, WEBSOCKET_URL


def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from dictionaries(item)
    elif isinstance(value, list):
        for item in value:
            yield from dictionaries(item)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ai", action="store_true", help="Also require a fresh AI diagnosis"
    )
    args = parser.parse_args()
    started = time.time()
    response = requests.get(CLIENT_URL + "/", timeout=10)
    response.raise_for_status()
    sample = next((ROOT / "past" / "csv").glob("*.csv"))
    with sample.open("rb") as source:
        requests.post(
            API_URL + "/upload",
            files={"file": (sample.name, source)},
            timeout=30,
        ).raise_for_status()
    async with websockets.connect(WEBSOCKET_URL, max_size=10_000_000) as ws:
        await ws.send(
            msgpack.packb(
                [
                    1,
                    {
                        "session_id": "",
                        "page_name": "",
                        "page": {
                            "route": "/",
                            "web": True,
                            "width": 1440,
                            "height": 1000,
                        },
                    },
                ]
            )
        )
        clicked = False
        completed = False
        while not completed:
            frame = await asyncio.wait_for(ws.recv(), timeout=650)
            message = msgpack.unpackb(frame, strict_map_key=False)
            assert message[0] != 6, message
            if message[0] == 1:
                assert not message[1].get("error"), message
            for control in dictionaries(message):
                content = control.get("content")
                if isinstance(content, str) and "분석 시작" in content and not clicked:
                    await ws.send(
                        msgpack.packb(
                            [
                                3,
                                {
                                    "target": control["_i"],
                                    "name": "click",
                                    "data": None,
                                },
                            ]
                        )
                    )
                    clicked = True
            text = str(message)
            assert "분석 실패:" not in text, text
            assert "❌ 오류:" not in text, text
            completed = clicked and "분석 완료!" in text
        result = {
            "http": response.status_code,
            "websocket": "OK",
            "analysis_button": "OK",
            "dashboard_update": "OK",
        }
        if args.ai:
            report = REPORT_DIR / "latest_diagnosis.txt"
            assert (
                report.exists() and report.stat().st_mtime >= started
            ), "No fresh AI report"
            diagnosis = report.read_text(encoding="utf-8")
            assert len(diagnosis) > 80 and not diagnosis.startswith(
                ("❌", "⚠")
            ), diagnosis
            result["ai_diagnosis"] = "OK"
            result["flow_seconds"] = round(time.time() - started, 1)
        (REPORT_DIR / "web_check.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
