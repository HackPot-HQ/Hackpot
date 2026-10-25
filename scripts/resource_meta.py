"""Collect every GitHub repository linked from the READMEs and record its
star count and last commit date on the default branch.

Writes meta/resources-meta.json, consumed by scripts/build_site.py.
Run from the weekly link-check workflow (authenticated via GITHUB_TOKEN).
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from links_common import extract_github_slugs  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.github.com"
UA = "hackpot-link-ci"


def gather_slugs():
    slugs = set()
    for readme in sorted(ROOT.rglob("README.md")):
        rel = readme.relative_to(ROOT).as_posix()
        if rel.startswith((".git/", "docs/", "site/", ".atl/")):
            continue
        slugs |= extract_github_slugs(readme.read_text(encoding="utf-8"))
    return slugs


def api_get(path, token):
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response), response.headers


def fetch_repo(slug, token):
    repo, _headers = api_get(f"/repos/{slug}", token)
    entry = {
        "stars": repo.get("stargazers_count"),
        "default_branch": repo.get("default_branch") or "HEAD",
        "pushed_at": repo.get("pushed_at"),
        "last_update": None,
        "not_found": False,
    }
    try:
        commits, _ = api_get(
            f"/repos/{slug}/commits?sha={entry['default_branch']}&per_page=1", token
        )
        if commits:
            entry["last_update"] = commits[0]["commit"]["committer"]["date"][:10]
    except (urllib.error.HTTPError, KeyError, IndexError):
        if entry["pushed_at"]:
            entry["last_update"] = entry["pushed_at"][:10]
    return entry


def load_previous(out_path):
    if out_path.exists():
        try:
            return json.loads(out_path.read_text(encoding="utf-8")).get("repos", {})
        except (ValueError, OSError):
            pass
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(ROOT / "meta" / "resources-meta.json"),
        help="Path of the metadata JSON to write.",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Debug: process at most N repos."
    )
    args = parser.parse_args()
    out_path = pathlib.Path(args.out)
    token = os.environ.get("GITHUB_TOKEN", "")

    slugs = sorted(gather_slugs())
    if args.limit:
        slugs = slugs[: args.limit]
    print(f"Found {len(slugs)} unique GitHub repository link(s).")

    previous = load_previous(out_path)
    repos, failures = {}, []
    for slug in slugs:
        try:
            repos[slug] = fetch_repo(slug, token)
            print(f"  ok   {slug}  stars={repos[slug]['stars']}")
        except urllib.error.HTTPError as error:
            if error.code in (403, 429) and "rate limit" in str(error).lower():
                print(f"  WARN rate limited at {slug}; reusing previous data.", file=sys.stderr)
                repos[slug] = previous.get(slug, {"not_found": False})
                failures.append(slug)
                continue
            if error.code == 404:
                repos[slug] = {"stars": None, "last_update": None,
                               "pushed_at": None, "not_found": True}
                print(f"  404  {slug} (repo missing or private)")
            else:
                print(f"  ERROR {slug}: HTTP {error.code}", file=sys.stderr)
                repos[slug] = previous.get(slug, {"not_found": False})
                failures.append(slug)
        except OSError as error:
            print(f"  ERROR {slug}: {error}", file=sys.stderr)
            repos[slug] = previous.get(slug, {"not_found": False})
            failures.append(slug)

    meta = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rate_limited": bool(failures),
        "repos": repos,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out_path} ({len(repos)} repos, {len(failures)} degraded).")


if __name__ == "__main__":
    main()
