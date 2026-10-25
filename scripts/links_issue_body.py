"""Turn a lychee JSON report into a GitHub issue body.

Usage: python scripts/links_issue_body.py <lychee-report.json> <out.md>
Prints one tri-state sentinel: 'broken' (body written), 'healthy' (clean scan),
or 'unknown' (unreadable or schema-drifted report — callers must not close
issues and should fail loudly).
"""

import json
import os
import sys


def normalize(entry):
    """Extract (url, source, error) from one lychee failure record, defensively."""
    if isinstance(entry, str):
        return entry, "", ""
    if isinstance(entry, dict):
        if "url" in entry:
            source = entry.get("source") or {}
            path = source.get("path", "") if isinstance(source, dict) else str(source)
            error = (
                entry.get("error")
                or entry.get("reason")
                or entry.get("status")
                or entry.get("context")
                or ""
            )
            return entry["url"], str(path), str(error)
        if len(entry) == 1:
            (url, info), = entry.items()
            if isinstance(info, dict):
                source = info.get("source") or {}
                path = source.get("path", "") if isinstance(source, dict) else str(source)
                error = (
                    info.get("error")
                    or info.get("reason")
                    or info.get("status")
                    or info.get("context")
                    or ""
                )
                return str(url), str(path), str(error)
            return str(url), "", str(info)
    return str(entry), "", ""


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    report_path, out_path = sys.argv[1], sys.argv[2]

    try:
        with open(report_path, encoding="utf-8-sig") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"Could not read lychee report: {error}", file=sys.stderr)
        print("unknown")
        sys.exit(0)

    if not isinstance(report, dict) or "failures" not in report:
        # Missing key or schema drift: never interpret as healthy.
        print("Report lacks expected 'failures' key.", file=sys.stderr)
        print("unknown")
        sys.exit(0)

    raw = report["failures"]
    if isinstance(raw, dict):
        raw = [{url: info} for url, info in raw.items()]
    if not isinstance(raw, list):
        print("unexpected 'failures' type", file=sys.stderr)
        print("unknown")
        sys.exit(0)
    failures = [normalize(item) for item in raw]

    if not failures:
        # Healthy only with positive schema evidence, never by absence of data.
        if isinstance(report.get("successes"), list):
            print("healthy")
        else:
            print("Empty failures without 'successes' evidence.", file=sys.stderr)
            print("unknown")
        sys.exit(0)

    run_url = ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    if repo and run_id:
        run_url = f"{server}/{repo}/actions/runs/{run_id}"

    by_source = {}
    for url, source, error in failures:
        by_source.setdefault(source or "(unknown source)", []).append((url, error))

    lines = [
        f"The weekly link check found **{len(failures)} broken link(s)**.",
        "",
    ]
    for source in sorted(by_source):
        lines.append(f"### `{source}`")
        lines.append("")
        for url, error in sorted(by_source[source]):
            suffix = f" — {error}" if error else ""
            lines.append(f"- [ ] `{url}`{suffix}")
        lines.append("")
    checked = os.environ.get("CHECK_DATE", "")
    footer = f"Automated report · last checked: {checked}" if checked else "Automated report."
    if run_url:
        footer += f" · [workflow run]({run_url})"
    lines.append(f"<sub>{footer}</sub>")
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("broken")


if __name__ == "__main__":
    main()
