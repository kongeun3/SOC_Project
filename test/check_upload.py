"""Exercise the browser FilePicker upload and same-server API handoff."""

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import msgpack
import requests
import websockets
from config import (
    CLIENT_URL,
    ROOT,
    UPLOAD_DIR,
    WEB_UPLOAD_DIR,
    WEBSOCKET_URL,
    REPORT_DIR,
)
from check_web import dictionaries


async def main():
    sample = ROOT / "test" / "test.jpg"
    clicked = False
    async with websockets.connect(WEBSOCKET_URL, max_size=10_000_000) as ws:
        await ws.send(
            msgpack.packb(
                [
                    1,
                    {
                        "session_id": "",
                        "page_name": "",
                        "page": {"route": "/", "web": True},
                    },
                ]
            )
        )
        for _ in range(40):
            message = msgpack.unpackb(
                await asyncio.wait_for(ws.recv(), 30), strict_map_key=False
            )
            assert message[0] != 6, message
            for control in dictionaries(message):
                if (
                    not clicked
                    and control.get("_c") == "Button"
                    and "이미지 업로드" in str(control.get("content", ""))
                ):
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
            if message[0] == 5:
                body = message[1]
                if body["name"] == "pick_files":
                    result = [
                        {
                            "id": "test-file",
                            "name": sample.name,
                            "size": sample.stat().st_size,
                            "path": None,
                        }
                    ]
                elif body["name"] == "upload":
                    upload = body["args"]["files"][0]
                    response = requests.put(
                        urljoin(CLIENT_URL, upload["upload_url"]),
                        data=sample.read_bytes(),
                        timeout=30,
                    )
                    response.raise_for_status()
                    result = None
                else:
                    raise AssertionError(body["name"])
                await ws.send(
                    msgpack.packb(
                        [
                            5,
                            {
                                "control_id": body["control_id"],
                                "call_id": body["call_id"],
                                "result": result,
                                "error": "",
                            },
                        ]
                    )
                )
            if "업로드 성공" in str(message):
                expected = hashlib.sha256(sample.read_bytes()).digest()
                browser_file = WEB_UPLOAD_DIR / sample.name
                api_file = max(
                    UPLOAD_DIR.glob("*_test.jpg"), key=lambda p: p.stat().st_mtime
                )
                assert hashlib.sha256(browser_file.read_bytes()).digest() == expected
                assert hashlib.sha256(api_file.read_bytes()).digest() == expected
                report = {
                    "server": CLIENT_URL,
                    "browser_upload": "OK",
                    "api_handoff": "OK",
                    "file_integrity": "OK",
                }
                (REPORT_DIR / "upload_check.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                print(report)
                return
        raise AssertionError("Upload completion was not received")


if __name__ == "__main__":
    asyncio.run(main())
