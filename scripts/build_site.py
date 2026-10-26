"""Generate the Hackpot GitHub Pages site from the README tree.

The READMEs are the single source of truth: this script mirrors them into
docs/ (git-ignored), rewrites relative links for Zensical, injects star and
freshness badges for GitHub repositories (from meta/resources-meta.json),
aggregates inline backtick tags into page front matter, and writes the
site configuration. Run by .github/workflows/deploy-docs.yml.
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
TAG_TOKEN_RE = re.compile(r"`([^`\n]+)`")
TAG_TYPE_PREFIX = "type:"
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
            return " · \u26a0\ufe0f **repo not found**"
        parts = []
        if entry.get("stars") is not None:
            parts.append(f"**★ {format_stars(entry['stars'])}**")
        if entry.get("last_update"):
            parts.append(f"updated {entry['last_update']}")
        return " · " + " · ".join(parts) if parts else ""
    return ""


TRAILING_TAGS_RE = re.compile(r"(?:\s*\x60[^\x60\n]+\x60)+\s*$")


def strip_trailing_tags(line):
    """Drop the trailing tag-token run of an entry line, keeping any inline
    code inside the description (tags are always last per CONTRIBUTING)."""
    return TRAILING_TAGS_RE.sub("", line).rstrip()


def transform(text, meta, repo_url, drop_tag_tokens=False):
    out_lines = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if FORMAT_COMMENT_RE.match(line):
            continue
        line = README_LINK_RE.sub(r"](\1index.md)", line)
        line = CONTRIB_LINK_RE.sub(r"](\1contributing.md)", line)
        if LICENSE_LINK_RE.search(line):
            if repo_url:
                line = line.replace("[LICENSE](LICENSE)", f"[LICENSE]({repo_url}/blob/main/LICENSE)")
            else:
                line = line.replace("[LICENSE](LICENSE)", "`LICENSE`")
        if LIST_ITEM_RE.match(line) and not in_fence:
            if drop_tag_tokens:
                # S3: tags render only as footer bubbles (from front matter),
                # so the trailing tag tokens leave the entry text. Fenced
                # example bullets (docs) are left completely untouched.
                line = strip_trailing_tags(line)
            line = line.rstrip() + badge_suffix(line, meta)
        out_lines.append(line)
    return "\n".join(out_lines)


def page_tags(text):
    """Unique tags from inline backtick tokens on list-item lines.

    `type:tool`-style tokens contribute their value (tool); plain tokens
    (free, osint, ...) are kept raw. Feeds Zensical's native tags plugin so
    entries' tags are searchable and filterable at page level (S2)."""
    tags = []
    for line in text.split("\n"):
        if not LIST_ITEM_RE.match(line):
            continue
        for token in TAG_TOKEN_RE.findall(line):
            token = token.strip()
            if token.startswith(TAG_TYPE_PREFIX):
                token = token[len(TAG_TYPE_PREFIX):].strip()
            if token and token not in tags:
                tags.append(token)
    return tags


def front_matter(tags):
    if not tags:
        return ""
    lines = ["---", "tags:"]
    lines += [f"- {yaml_quote(tag)}" for tag in tags]
    lines.append("---")
    return "\n".join(lines) + "\n"


def convert(source, dest, meta, repo_url, tagged=False):
    text = source.read_text(encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tags = page_tags(transform(text, meta, repo_url)) if tagged else []
    body = transform(text, meta, repo_url, drop_tag_tokens=tagged)
    dest.write_text(front_matter(tags) + body, encoding="utf-8")
    return dest.relative_to(DOCS).as_posix()


def yaml_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def page_title(path):
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    return first.lstrip("#").strip() or path.parent.name.replace("_", " ")


# Nightshell theme (user-selected prototype P1, odd/tasks/docs-style-nightshell.md S2).
# Fonts load from Google's CDN; swap to self-hosted woff2 for data-privacy if desired.
THEME_CSS = """@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=JetBrains+Mono:wght@400;600;700&display=swap');
.md-typeset { font-family: "Inter", -apple-system, sans-serif; }
.md-typeset h1, .md-typeset h2, .md-typeset h3 { font-family: "JetBrains Mono", monospace; letter-spacing: -0.02em; }
.md-typeset code, .md-typeset pre { font-family: "JetBrains Mono", monospace; }
[data-md-color-scheme="slate"] { --md-default-bg-color: #0a0f14; --md-code-bg-color: #0d1520; --md-typeset-a-color: #34d399; }
.md-banner { background: #052e16; color: #6ee7b7; font-family: "JetBrains Mono", monospace; font-size: .75em; }
.hp-hero { background: linear-gradient(180deg, #020617, #052e16); border: 1px solid #10b98155; border-radius: 12px; padding: 2.2rem 2rem; margin: 1.5rem 0; color: #d1fae5; }
.hp-hero .prompt { font-family: "JetBrains Mono", monospace; color: #34d399; font-size: .95rem; }
.hp-hero .cursor::after { content: "\u258b"; animation: blink 1.1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.hp-hero h2 { color: #ecfdf5; margin: .6rem 0 .2rem; }
.hp-hero p { color: #a7f3d0; }
.hp-chips { margin-top: 1rem; display: flex; gap: .5rem; flex-wrap: wrap; }
.hp-chips span { font-family: "JetBrains Mono", monospace; font-size: .72rem; padding: .25rem .7rem; border-radius: 999px; background: #064e3b; color: #6ee7b7; border: 1px solid #10b98144; }
.md-tag { background: #022c22 !important; color: #6ee7b7 !important; border: 1px solid #10b98155; border-radius: 999px; font-family: "JetBrains Mono", monospace; }
[data-md-color-scheme="default"] .md-tag { background: #d1fae5 !important; color: #065f46 !important; border-color: #10b98155; }
.md-content table { border-radius: 10px; overflow: hidden; }
.md-content tbody tr:hover { background: #0596690f; }
"""

HOME_HERO = """<div class="hp-hero">
  <div class="prompt">root@hackpot:~$ ./jackpot --catalog all <span class="cursor"></span></div>
  <h2>The jackpot of pentesting resources</h2>
  <p>Category-first, curated, CI-verified. Tools, courses, wordlists, labs and reading — across the whole kill chain.</p>
  <div class="hp-chips"><span>17 categories</span><span>weekly link checks</span><span>star &amp; freshness badges</span><span>search by name + tag</span></div>
</div>

"""

# S4: the native tags plugin (adapted from Material's tags plugin) renders a
# whole-site tag index at this marker, and turns each page's tags into links
# that jump to their entry in it. Material's marker, not mkdocs-plugin-tags'.
TAGS_PAGE = """# Tags

Every tag used across the catalog. Pick one to filter the site —
or filter search results by tag from the search bar.

<!-- material/tags -->
"""


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
    home = DOCS / "index.md"
    home_text = home.read_text(encoding="utf-8")
    if "## Categories" in home_text:
        home.write_text(
            home_text.replace("## Categories", HOME_HERO + "## Categories", 1),
            encoding="utf-8")
    if (ROOT / "CONTRIBUTING.md").exists():
        convert(ROOT / "CONTRIBUTING.md", DOCS / "contributing.md", meta, repo_url)
        nav.append(("Contributing", "contributing.md"))
    (DOCS / "tags.md").write_text(TAGS_PAGE, encoding="utf-8")
    nav.append(("Tags", "tags.md"))

    category_pages = []
    for category_dir in sorted(
        p for p in ROOT.iterdir() if p.is_dir() and CATEGORY_DIR_RE.match(p.name)
    ):
        cat_title = page_title(category_dir / "README.md")
        cat_nav = []
        cat_file = f"{category_dir.name}/index.md"
        convert(category_dir / "README.md", DOCS / cat_file, meta, repo_url, tagged=True)
        cat_nav.append(("Overview", cat_file))
        for leaf_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            leaf_title = page_title(leaf_dir / "README.md")
            leaf_file = f"{category_dir.name}/{leaf_dir.name}/index.md"
            convert(leaf_dir / "README.md", DOCS / leaf_file, meta, repo_url, tagged=True)
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
    styles = DOCS / "stylesheets"
    styles.mkdir(parents=True, exist_ok=True)
    (styles / "theme.css").write_text(THEME_CSS, encoding="utf-8")

    yaml_lines = [
        f"site_name: {yaml_quote('Hackpot — the jackpot of pentesting resources')}",
        f"docs_dir: {yaml_quote(DOCS.name)}",
        "site_dir: \"site\"",
        "use_directory_urls: true",
    ]
    if repo_url:
        yaml_lines.append(f"repo_url: {yaml_quote(repo_url)}")
        yaml_lines.append("edit_uri: \"\"")
    yaml_lines += [
        "theme:",
        "  variant: \"classic\"",
        "  custom_dir: \"docs/overrides\"",
        "  language: \"en\"",
        "  features:",
        "    - \"navigation.sections\"",
        "    - \"navigation.top\"",
        "    - \"navigation.footer\"",
        "    - \"toc.follow\"",
        "    - \"search.highlight\"",
        "  palette:",
        "    - media: \"(prefers-color-scheme)\"",
        "      toggle:",
        "        icon: \"lucide/sun-moon\"",
        "        name: \"Switch to light mode\"",
        "    - media: \"(prefers-color-scheme: light)\"",
        "      scheme: \"default\"",
        "      primary: \"#047857\"",
        "      accent: \"#10b981\"",
        "      toggle:",
        "        icon: \"lucide/sun\"",
        "        name: \"Switch to dark mode\"",
        "    - media: \"(prefers-color-scheme: dark)\"",
        "      scheme: \"slate\"",
        "      primary: \"#022c22\"",
        "      accent: \"#34d399\"",
        "      toggle:",
        "        icon: \"lucide/moon\"",
        "        name: \"Switch to system preference\"",
        "extra_css:",
        "  - \"stylesheets/theme.css\"",
        "plugins:",
        "  - search",
        "  - tags",
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
    # Zensical requires site_dir within the project root (= config dir),
    # so the config lives at the repo root, not inside docs/.
    (DOCS.parent / "mkdocs.yml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
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
