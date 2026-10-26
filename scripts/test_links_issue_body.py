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
    # Real lychee v0.24.2 --format json shapes: top-level counters are plain
    # ints (no 'total.successful' dict) and failures carry status.details/span.
    ("lychee 0.24 map schema with errors", {
        "total": 3, "unique": 3, "successful": 1, "errors": 1, "excludes": 1,
        "success_map": SUCCESS,
        "error_map": {"a.md": [{"url": "https://httpbin.org/status/404",
                                "status": {"text": "Network error: Permission denied",
                                           "details": "Permission denied"},
                                "span": {"line": 5, "column": 1}}]},
        "timeout_map": {}, "suggestion_map": {}, "redirect_map": {},
        "detailed_stats": True,
    }, "broken"),
    ("lychee 0.24 clean scan, counters only (no verbose)", {
        "total": 5, "unique": 5, "successful": 5, "errors": 0,
        "success_map": {}, "error_map": {}, "timeout_map": {},
        "detailed_stats": False,
    }, "healthy"),
    ("lychee 0.24 nothing scanned, only excludes", {
        "total": 2, "unique": 2, "successful": 0, "errors": 0, "excludes": 2,
        "success_map": {}, "error_map": {}, "timeout_map": {},
        "detailed_stats": False,
    }, "unknown"),
    ("plain failures list with entries", {
        "failures": [{"url": "https://x/1", "source": {"path": "a.md"}, "status": "404"}],
    }, "broken"),
    ("plain list empty both", {"failures": [], "successes": []}, "unknown"),
    ("plain list healthy", {"failures": [], "successes": [{"url": "x"}]}, "healthy"),
    # JSON true must not pass as a positive scan counter (bool is an int subclass).
    ("boolean successful is not evidence", {
        "total": 2, "unique": 2, "successful": True, "errors": 0,
        "success_map": {}, "error_map": {}, "timeout_map": {},
    }, "unknown"),
]

# A 'broken' body must mirror exactly what the failure maps hold.
BROKEN_REPORT = {
    "total": 4, "unique": 4, "successful": 1, "errors": 2, "timeouts": 1,
    "success_map": {"README.md": [{"url": "https://ok/1", "status": {"text": "200 OK"}}]},
    "error_map": {"a.md": [
        {"url": "https://bad/1", "status": {"text": "Not Found", "code": 404}},
        {"url": "https://bad/2", "status": {"text": "Gone", "code": 410}}]},
    "timeout_map": {"b.md": [{"url": "https://slow/1", "status": {"text": "Timed out"}}]},
}
BROKEN_LINES = [
    "The weekly link check found **3 broken link(s)**.",
    "### `a.md`", "### `b.md`",
    "- [ ] `https://bad/1` — Not Found (404)",
    "- [ ] `https://bad/2` — Gone (410)",
    "- [ ] `https://slow/1` — Timed out",
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
        # Broken-report bodies are the human-facing artifact: pin its content.
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(BROKEN_REPORT, handle)
        if os.path.exists(body):
            os.remove(body)
        result = subprocess.run(
            [sys.executable, SCRIPT, report, body],
            capture_output=True, text=True, timeout=30,
        )
        text = open(body, encoding="utf-8").read() if os.path.exists(body) else ""
        missing = [line for line in BROKEN_LINES if line not in text]
        if result.stdout.strip() != "broken" or missing or "https://ok/1" in text \
                or text.count("- [ ] `") != len(BROKEN_REPORT["error_map"]["a.md"]) + 1:
            failures += 1
            print(f"FAIL broken body fidelity: got {result.stdout.strip()!r} "
                  f"missing={missing} successes leaked={'https://ok/1' in text}")
        else:
            print("ok   broken body fidelity")
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
