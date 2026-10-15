"""Check a running Flet UI through its FilePicker, jobs and private images."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from config import ROOT, REPORT_DIR, CLIENT_URL
from check_upload import flet_flow


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", action="store_true", help="Require a successful AI diagnosis")
    args = parser.parse_args()
    response = requests.get(CLIENT_URL + "/", timeout=10)
    response.raise_for_status()
    sample = next((ROOT / "past" / "csv").glob("*.csv"), ROOT / "test" / "test.jpg")
    result = await flet_flow(sample, analyze=True, require_ai=args.ai)
    result.update(http=response.status_code, websocket="OK")
    (REPORT_DIR / "web_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
