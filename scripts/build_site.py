"""Generate the Hackpot GitHub Pages site from the README tree.

The READMEs are the single source of truth: this script mirrors them into
docs/ (git-ignored), rewrites relative links for mkdocs, injects star and
freshness badges for GitHub repositories (from meta/resources-meta.json),
and writes the mkdocs configuration. Run by .github/workflows/deploy-docs.yml.
"""

import argparse
import datetime
import json
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from links_common import GITHUB_URL_RE, github_slug  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD_MARKER = ".hackpot_build"

README_LINK_RE = re.compile(r"\]\(([^)#\s]*)README\.md\)")
CONTRIB_LINK_RE = re.compile(r"\]\(([^)#\s]*)CONTRIBUTING\.md\)")
LICENSE_LINK_RE = re.compile(r"\[LICENSE\]\(LICENSE\)")
LIST_ITEM_RE = re.compile(r"^\s*[-*] \[")
FORMAT_COMMENT_RE = re.compile(r"^\s*<!--\s*Format:")
CATEGORY_DIR_RE = re.compile(r"^\d{2}_")


def load_meta():
    path = ROOT / "meta" / "resources-meta.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_repo_url():
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    return f"https://github.com/{match.group(1)}/{match.group(2)}" if match else None


def format_stars(count):
    if count >= 100_000:
        return f"{count / 1000:.0f}k"
    if count >= 1_000:
        return f"{count / 1000:.1f}k"
    return str(count)


def badge_suffix(line, meta):
    """Badge text for the first GitHub repo link in a list item, '' if none."""
    repos = meta.get("repos") or {}
    for url in GITHUB_URL_RE.findall(line):
        slug = github_slug(url)
        entry = repos.get(slug) if slug else None
        if not entry:
            continue
        if entry.get("not_found"):
            return " · :warning: **repo not found**"
        parts = []
        if entry.get("stars") is not None:
            parts.append(f"**★ {format_stars(entry['stars'])}**")
        if entry.get("last_update"):
            parts.append(f"updated {entry['last_update']}")
        return " · " + " · ".join(parts) if parts else ""
    return ""


def transform(text, meta, repo_url):
    out_lines = []
    for line in text.split("\n"):
        if FORMAT_COMMENT_RE.match(line):
            continue
        line = README_LINK_RE.sub(r"](\1index.md)", line)
        line = CONTRIB_LINK_RE.sub(r"](\1contributing.md)", line)
        if LICENSE_LINK_RE.search(line):
            if repo_url:
                line = line.replace("[LICENSE](LICENSE)", f"[LICENSE]({repo_url}/blob/main/LICENSE)")
            else:
                line = line.replace("[LICENSE](LICENSE)", "`LICENSE`")
        if LIST_ITEM_RE.match(line):
            line = line.rstrip() + badge_suffix(line, meta)
        out_lines.append(line)
    return "\n".join(out_lines)


def convert(source, dest, meta, repo_url):
    text = source.read_text(encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(transform(text, meta, repo_url) , encoding="utf-8")
    return dest.relative_to(DOCS).as_posix()


def yaml_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def page_title(path):
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    return first.lstrip("#").strip() or path.parent.name.replace("_", " ")


def build(out_dir, repo_url):
    global DOCS
    DOCS = out_dir
    if DOCS.exists():
        if not (DOCS / BUILD_MARKER).exists():
            sys.exit(f"refusing to clean {DOCS}: no {BUILD_MARKER} file (not a generated build)")
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)
    (DOCS / BUILD_MARKER).write_text("", encoding="utf-8")

    meta = load_meta()

    nav = []
    convert(ROOT / "README.md", DOCS / "index.md", meta, repo_url)
    nav.append(("Home", "index.md"))
    if (ROOT / "CONTRIBUTING.md").exists():
        convert(ROOT / "CONTRIBUTING.md", DOCS / "contributing.md", meta, repo_url)
        nav.append(("Contributing", "contributing.md"))

    category_pages = []
    for category_dir in sorted(
        p for p in ROOT.iterdir() if p.is_dir() and CATEGORY_DIR_RE.match(p.name)
    ):
        cat_title = page_title(category_dir / "README.md")
        cat_nav = []
        cat_file = f"{category_dir.name}/index.md"
        convert(category_dir / "README.md", DOCS / cat_file, meta, repo_url)
        cat_nav.append(("Overview", cat_file))
        for leaf_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            leaf_title = page_title(leaf_dir / "README.md")
            leaf_file = f"{category_dir.name}/{leaf_dir.name}/index.md"
            convert(leaf_dir / "README.md", DOCS / leaf_file, meta, repo_url)
            cat_nav.append((leaf_title, leaf_file))
        category_pages.append((f"{category_dir.name[:2]} · {cat_title}", cat_nav))
    nav.extend(category_pages)

    checked = meta.get("checked_at")
    if checked:
        checked_display = checked[:10]
    else:
        checked_display = "not yet (the check runs weekly in CI)"
    banner = (
        '{% extends "base.html" %}\n'
        "{% block announce %}\n"
        "🔗 Links, stars and freshness last checked by CI: "
        f"<strong>{checked_display}</strong>\n"
        "{% endblock %}\n"
    )
    overrides = DOCS / "overrides"
    overrides.mkdir(parents=True, exist_ok=True)
    (overrides / "main.html").write_text(banner, encoding="utf-8")

    yaml_lines = [
        f"site_name: {yaml_quote('Hackpot — the jackpot of pentesting resources')}",
        "docs_dir: \".\"",
        "use_directory_urls: true",
    ]
    if repo_url:
        yaml_lines.append(f"repo_url: {yaml_quote(repo_url)}")
        yaml_lines.append("edit_uri: \"\"")
    yaml_lines += [
        "theme:",
        "  name: \"material\"",
        "  custom_dir: \"overrides\"",
        "  language: \"en\"",
        "  features:",
        "    - \"navigation.sections\"",
        "    - \"navigation.top\"",
        "    - \"navigation.footer\"",
        "    - \"toc.follow\"",
        "plugins:",
        "  - search",
        "markdown_extensions:",
        "  - toc:",
        "      permalink: true",
        "nav:",
    ]
    for label, value in nav:
        if isinstance(value, str):
            yaml_lines.append(f"  - {yaml_quote(label)}: {yaml_quote(value)}")
        else:
            yaml_lines.append(f"  - {yaml_quote(label)}:")
            for child_label, child_file in value:
                yaml_lines.append(
                    f"      - {yaml_quote(child_label)}: {yaml_quote(child_file)}"
                )
    (DOCS / "mkdocs.yml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    print(f"Generated {sum(1 for _ in DOCS.rglob('*.md'))} pages into {DOCS}")
    print(f"Metadata checked_at: {checked_display}; "
          f"{len(meta.get('repos') or {})} repo entries loaded.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "docs"), help="Output docs directory.")
    parser.add_argument("--repo-url", default=None, help="Override repository URL.")
    args = parser.parse_args()
    build(pathlib.Path(args.out), args.repo_url or detect_repo_url())


if __name__ == "__main__":
    main()
