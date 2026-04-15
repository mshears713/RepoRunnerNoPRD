#!/usr/bin/env python3
"""
End-to-end smoke test.
Submits a known-good public repo, polls for completion, and asserts results.

Usage:
  python scripts/e2e_smoke.py [--api-url http://localhost:8000] [--repo https://github.com/...]

WARNING: This triggers a real GitHub Codespace. Run manually before version tags only.
"""

import argparse
import json
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

DEFAULT_API = "http://localhost:8000"
DEFAULT_REPO = "https://github.com/tiangolo/full-stack-fastapi-template"
POLL_INTERVAL = 15
MAX_WAIT = 900  # 15 minutes


def api_get(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args()

    base = args.api_url.rstrip("/")
    print(f"[smoke] API: {base}")
    print(f"[smoke] Repo: {args.repo}")

    # Health check
    health = api_get(f"{base}/api/health")
    print(f"[smoke] Health: {health}")
    assert health["status"] == "ok", "Backend is not healthy"

    # Submit
    print("[smoke] Submitting scan...")
    result = api_post(
        f"{base}/api/scan",
        {
            "repo_url": args.repo,
            "summary": "Smoke test submission",
            "tags": ["smoke-test"],
        },
    )
    scan_id = result["id"]
    print(f"[smoke] Scan ID: {scan_id}")

    # Poll
    start = time.time()
    while time.time() - start < MAX_WAIT:
        scan = api_get(f"{base}/api/scan/{scan_id}")
        status = scan["status"]
        elapsed = int(time.time() - start)
        print(f"[smoke] [{elapsed}s] status={status}")

        if status == "completed":
            print("[smoke] ✓ Scan completed")
            analysis = scan.get("analysis")
            if analysis and analysis.get("what_it_does"):
                print(f"[smoke] ✓ Analysis: {analysis['what_it_does'][:100]}")
            else:
                print("[smoke] ⚠ Analysis is empty — check Gemini API key")
            preview = scan.get("preview_url")
            print(f"[smoke] Preview URL: {preview or 'none'}")
            print("[smoke] PASS")
            sys.exit(0)

        elif status == "failed":
            print("[smoke] ✗ Scan failed")
            failure = scan.get("failure")
            if failure:
                print(f"[smoke] Category: {failure.get('category')}")
                print(f"[smoke] Explanation: {failure.get('plain_explanation')}")
            print("[smoke] FAIL")
            sys.exit(1)

        time.sleep(POLL_INTERVAL)

    print(f"[smoke] TIMEOUT after {MAX_WAIT}s")
    sys.exit(2)


if __name__ == "__main__":
    main()
