"""Exercise two Flet browser uploads with the same original filename."""

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import msgpack
import requests
import websockets
from config import CLIENT_URL, ROOT, WEB_UPLOAD_DIR, WEBSOCKET_URL, REPORT_DIR


def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from dictionaries(item)
    elif isinstance(value, list):
        for item in value:
            yield from dictionaries(item)


def apply_message(controls, message):
    """Decode Flet's compact patches to observe the actual displayed state."""
    if message[0] == 1:
        roots = [message[1]["page_patch"]]
    elif message[0] == 2:
        body = message[1]
        target = controls[body["id"]]
        patch = body["patch"]
        paths = {}

        def index_paths(node, path):
            paths[node[0]] = path
            if len(node) > 1:
                for key, child in node[1].items():
                    index_paths(child, path + [key])

        def parent(index):
            node = target
            for key in paths[index]:
                node = node[key]
            return node

        index_paths(patch[0], [])
        for operation in patch[1:]:
            kind, path_index, key = operation[:3]
            node = parent(path_index)
            if kind == 0:
                node[key] = operation[3]
            elif kind == 1:
                if isinstance(node, list):
                    node.insert(key, operation[3])
                else:
                    node[key] = operation[3]
            elif kind == 2:
                del node[key]
            else:
                raise AssertionError(f"Unhandled Flet patch operation: {kind}")
        roots = [target]
    else:
        return
    for root in roots:
        for control in dictionaries(root):
            if "_i" in control:
                controls[control["_i"]] = control


async def flet_flow(sample, *, analyze=False, require_ai=False):
    """Upload and optionally analyze through one actual Flet page session."""
    started = time.monotonic()
    controls = {}
    upload_clicked = False
    upload_complete = False
    analysis_clicked = False
    staged_name = None
    analysis_button = None
    diagnosis_control = None
    diagnosis = ""
    image_ids = set()
    image_sources = {}

    async with websockets.connect(WEBSOCKET_URL, max_size=50_000_000) as ws:
        async def event(control_id, name="click"):
            await ws.send(msgpack.packb([3, {
                "target": control_id, "name": name, "data": None,
            }]))

        await ws.send(msgpack.packb([1, {
            "session_id": "", "page_name": "",
            "page": {"route": "/", "web": True, "width": 1440, "height": 1000},
        }]))
        while time.monotonic() - started < 3600:
            message = msgpack.unpackb(await asyncio.wait_for(ws.recv(), 900), strict_map_key=False)
            assert message[0] != 6, message
            if message[0] == 1:
                assert not message[1].get("error"), message
            apply_message(controls, message)
            for control_id, current in controls.items():
                if current.get("_c") == "Image":
                    image_ids.add(control_id)
                if control_id in image_ids and current.get("src"):
                    image_sources[control_id] = current["src"]
                content = current.get("content", "")
                if current.get("_c") == "Button" and isinstance(content, str):
                    if "이미지 업로드" in content and not upload_clicked:
                        await event(control_id)
                        upload_clicked = True
                    elif "분석 시작" in content:
                        analysis_button = control_id
                if current.get("value") == "분석 완료 후 AI 진단이 표시됩니다.":
                    diagnosis_control = control_id
                if control_id == diagnosis_control and "value" in current:
                    diagnosis = current["value"]

            if message[0] == 5:
                body = message[1]
                if body["name"] == "pick_files":
                    picked = [{
                        "id": "test-file", "name": sample.name,
                        "size": sample.stat().st_size, "path": None,
                    }]
                elif body["name"] == "upload":
                    upload = body["args"]["files"][0]
                    url = urljoin(CLIENT_URL, upload["upload_url"])
                    staged_name = parse_qs(urlsplit(url).query)["f"][0]
                    assert Path(staged_name).name == staged_name
                    assert staged_name != sample.name, "Flet staging must use a unique filename"
                    response = await asyncio.to_thread(
                        requests.put, url, data=sample.read_bytes(), timeout=60
                    )
                    response.raise_for_status()
                    picked = None
                else:
                    raise AssertionError(body["name"])
                await ws.send(msgpack.packb([5, {
                    "control_id": body["control_id"], "call_id": body["call_id"],
                    "result": picked, "error": "",
                }]))

            # Inspect text fields rather than serializing PNG byte payloads.
            text = "\n".join(
                str(item.get("value", "")) for item in controls.values()
                if isinstance(item.get("value"), str)
            )
            for failure in ("❌ 업로드", "❌ 오류:", "❌ 백엔드", "분석 실패:"):
                assert failure not in text, text
            upload_complete = upload_complete or "업로드 성공" in text
            if upload_complete and not analyze:
                break
            if (upload_complete and analyze and not analysis_clicked and analysis_button
                    and not controls[analysis_button].get("disabled", False)):
                await event(analysis_button)
                analysis_clicked = True
            if analysis_clicked and "분석 완료!" in text:
                assert len(image_sources) >= 4, "Dashboard did not receive its four images"
                assert all(isinstance(src, bytes) and src.startswith(b"\x89PNG")
                           for src in image_sources.values()), "Images must be private inline PNGs"
                if require_ai:
                    assert len(diagnosis) > 80 and not diagnosis.startswith(("❌", "⚠", "🤖")), diagnosis
                break
        else:
            raise AssertionError("Flet flow did not complete within an hour")

    assert staged_name and upload_complete, "Upload did not complete"
    staged = WEB_UPLOAD_DIR / staged_name
    expected = hashlib.sha256(sample.read_bytes()).digest()
    assert hashlib.sha256(staged.read_bytes()).digest() == expected
    report = {
        "browser_upload": "OK", "api_handoff": "OK", "file_integrity": "OK",
        "staging_file": staged_name,
    }
    if analyze:
        report.update(analysis_button="OK", dashboard_update="OK", private_images="OK")
        if require_ai:
            report["ai_diagnosis"] = "OK"
    report["flow_seconds"] = round(time.monotonic() - started, 1)
    return report


async def main():
    sample = ROOT / "test" / "test.jpg"
    results = await asyncio.gather(flet_flow(sample), flet_flow(sample))
    assert results[0]["staging_file"] != results[1]["staging_file"]
    report = {"server": CLIENT_URL, "same_name_concurrent_uploads": "OK", "sessions": results}
    (REPORT_DIR / "upload_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
