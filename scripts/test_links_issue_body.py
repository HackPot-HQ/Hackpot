"""Regression tests for scripts/links_issue_body.py (stdlib only, no runner needed).

Run: python scripts/test_links_issue_body.py
Covers the two escalated-review failure modes: false-healthy on evidence-less
reports, and schema drift never being read as 'healthy'.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "links_issue_body.py")
SUCCESS = {"README.md": [{"url": "https://a/1", "status": "200 OK"}]}

CASES = [
    ("map schema with failures", {
        "total": {"successful": 1, "errors": 1}, "success_map": SUCCESS,
        "error_map": {"a.md": [{"url": "https://dead", "status": {"text": "Not Found", "code": 404}}]},
        "timeout_map": {},
    }, "broken"),
    ("map schema clean with positive evidence", {
        "total": {"successful": 1, "errors": 0}, "success_map": SUCCESS,
        "error_map": {}, "timeout_map": {},
    }, "healthy"),
    ("map schema zero scanned without successes", {
        "total": {"successful": 0, "errors": 0}, "success_map": {},
        "error_map": {}, "timeout_map": {},
    }, "unknown"),
    ("schema drift renamed failure map", {
        "total": {"successful": 0, "timeouts": 9}, "success_map": {}, "failuures_map": {},
    }, "unknown"),
    ("legacy fail_map with errors", {
        "total": {"successful": 1}, "success_map": SUCCESS,
        "fail_map": {"a.md": [{"url": "https://x", "status": {"text": "410"}}]},
    }, "broken"),
    ("plain failures list with entries", {
        "failures": [{"url": "https://x/1", "source": {"path": "a.md"}, "status": "404"}],
    }, "broken"),
    ("plain list empty both", {"failures": [], "successes": []}, "unknown"),
    ("plain list healthy", {"failures": [], "successes": [{"url": "x"}]}, "healthy"),
]


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        body = os.path.join(tmp, "body.md")
        for label, data, expected in CASES:
            with open(report, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = subprocess.run(
                [sys.executable, SCRIPT, report, body],
                capture_output=True, text=True, timeout=30,
            )
            got = result.stdout.strip()
            if got != expected or result.returncode != 0:
                failures += 1
                print(f"FAIL {label}: got {got!r} rc={result.returncode} want {expected!r}")
            else:
                print(f"ok   {label}")
        # Unreadable and missing reports must never look healthy.
        for label, path in [("garbage report", report), ("missing report", os.path.join(tmp, "none.json"))]:
            if label == "garbage report":
                with open(report, "w", encoding="utf-8") as handle:
                    handle.write("not json at all")
            result = subprocess.run(
                [sys.executable, SCRIPT, path, body],
                capture_output=True, text=True, timeout=30,
            )
            if result.stdout.strip() != "unknown":
                failures += 1
                print(f"FAIL {label}: got {result.stdout.strip()!r} want 'unknown'")
            else:
                print(f"ok   {label}")
    if failures:
        print(f"{failures} regression test(s) FAILED", file=sys.stderr)
        sys.exit(1)
    print("All links_issue_body regressions pass.")


if __name__ == "__main__":
    main()
