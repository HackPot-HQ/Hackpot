"""Turn a lychee JSON report into a GitHub issue body.

Usage: python scripts/links_issue_body.py <lychee-report.json> <out.md>
Prints one tri-state sentinel: 'broken' (body written), 'healthy' (clean scan),
or 'unknown' (unreadable, schema-drifted, or evidence-less report — callers
must not close issues and should fail loudly). 'healthy' is printed only with
positive evidence that links were scanned successfully.

Supported report shapes:
- lychee's --format json stats: *_map dicts keyed by source ('error_map',
  'timeout_map' hold failures; 'success_map'/'total' prove the scan ran).
- a plain {'failures': [...], 'successes': [...]} object (older/other tools).
"""

import json
import os
import sys

FAILURE_MAPS = ("error_map", "timeout_map", "fail_map")


def _status_text(result):
    status = result.get("status")
    if isinstance(status, dict):
        text = status.get("text") or ""
        code = status.get("code")
        return f"{text} ({code})".strip() if code else str(text)
    return str(status or result.get("error") or result.get("reason") or "")


def flatten_map_schema(report):
    """(url, source, error) triples from lychee's map-shaped JSON."""
    triples = []
    for key in FAILURE_MAPS:
        data = report.get(key)
        if not isinstance(data, dict):
            continue
        for source, results in data.items():
            if isinstance(results, dict):
                results = list(results.values())
            elif not isinstance(results, (list, tuple)):
                results = [results]
            for result in results:
                if isinstance(result, dict):
                    triples.append((str(result.get("url", "")), str(source),
                                    _status_text(result)))
                elif result:
                    triples.append((str(result), str(source), ""))
    return triples


def normalize(entry):
    """Extract (url, source, error) from one failure record of the list shape."""
    if isinstance(entry, str):
        return entry, "", ""
    if isinstance(entry, dict):
        if "url" in entry:
            source = entry.get("source") or {}
            path = source.get("path", "") if isinstance(source, dict) else str(source)
            return entry["url"], str(path), _status_text(entry)
        if len(entry) == 1:
            (url, info), = entry.items()
            if isinstance(info, dict):
                source = info.get("source") or {}
                path = source.get("path", "") if isinstance(source, dict) else str(source)
                return str(url), str(path), _status_text(info)
            return str(url), "", str(info)
    return str(entry), "", ""


def unknown(reason):
    print(reason, file=sys.stderr)
    print("unknown")
    sys.exit(0)


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    report_path, out_path = sys.argv[1], sys.argv[2]

    try:
        with open(report_path, encoding="utf-8-sig") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as error:
        unknown(f"Could not read lychee report: {error}")

    if not isinstance(report, dict):
        unknown("Report is not a JSON object.")

    map_schema = all(isinstance(report.get(k), dict) for k in ("success_map", "error_map", "timeout_map"))
    legacy_map_schema = all(isinstance(report.get(k), dict) for k in ("success_map", "fail_map"))
    if map_schema or legacy_map_schema:
        failures = flatten_map_schema(report)
        if failures:
            pass
        elif report.get("success_map") or (
            isinstance(report.get("total"), dict)
            and isinstance(report["total"].get("successful"), int)
            and report["total"]["successful"] > 0
        ):
            print("healthy")
            sys.exit(0)
        else:
            unknown("Attested schema but no positive scan evidence (zero or hidden successes).")
    elif isinstance(report.get("failures"), list):
        failures = [normalize(item) for item in report["failures"]]
        if not failures:
            if isinstance(report.get("successes"), list) and report["successes"]:
                print("healthy")
                sys.exit(0)
            unknown("Empty failures list without positive 'successes' evidence.")
    else:
        unknown("Report matches neither the lychee map schema nor a failures list.")

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
