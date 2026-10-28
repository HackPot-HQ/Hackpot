"""Generate the Hackpot GitHub Pages site from the README tree.

The READMEs are the single source of truth: this script mirrors them into
docs/ (git-ignored), rewrites relative links for Zensical, injects star and
freshness badges for GitHub repositories (from meta/resources-meta.json),
aggregates inline backtick tags into page front matter, and writes the
site configuration. Run by .github/workflows/deploy-docs.yml.
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import date

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


def format_date(iso):
    """Render-only ISO YYYY-MM-DD -> DD-MM-YYYY; stored metadata stays ISO.

    Used by the no-reference fallback pill; age display never reaches here."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else (iso or "")


def parse_day(iso):
    """Leading YYYY-MM-DD of an ISO stamp -> date, or None if unparsable."""
    try:
        return date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def commit_tier(days):
    """Option A traffic light: fresh <=30d (emerald base palette), active
    <=180d (lime), aging <=365d (amber), dormant >365d (red)."""
    if days <= 30:
        return "fresh"
    if days <= 180:
        return "active"
    if days <= 365:
        return "aging"
    return "dormant"


def format_age(days):
    """"Nd" under a year; "Yy Dd" at or above 365d on a 365-day year,
    bare "Yy" when the remainder is 0."""
    if days < 365:
        return f"{days}d"
    years, rem = divmod(days, 365)
    return f"{years}y" if rem == 0 else f"{years}y {rem}d"


STARS_BADGE = '<span class="hp-badge hp-badge--stars">\u2605 {}</span>'
COMMIT_BADGE = ('<span class="hp-badge hp-badge--commit hp-badge--commit-{}">'
                'last commit {}</span>')
COMMIT_BADGE_DATED = '<span class="hp-badge hp-badge--commit">last commit {}</span>'
BROKEN_BADGE = '<span class="hp-badge hp-badge--broken">\u26a0\ufe0f repo not found</span>'


def commit_badge(entry, meta):
    """Freshness pill for one repo entry: age vs meta checked_at with an
    Option A tier class, or the absolute DD-MM-YYYY date when the metadata
    gives no usable reference (pre-refresh builds, corrupt stamps)."""
    reference = parse_day(meta.get("checked_at"))
    updated = parse_day(entry["last_update"])
    if reference is None or updated is None:
        return COMMIT_BADGE_DATED.format(format_date(entry["last_update"]))
    days = max((reference - updated).days, 0)
    return COMMIT_BADGE.format(commit_tier(days), format_age(days))


def badge_suffix(line, meta):
    """Badge text for the first GitHub repo link in a list item, '' if none.

    Badges are theme-styled chip spans; the palette lives in THEME_CSS so
    light/dark schemes are handled in CSS."""
    repos = meta.get("repos") or {}
    for url in GITHUB_URL_RE.findall(line):
        slug = github_slug(url)
        entry = repos.get(slug) if slug else None
        if not entry:
            continue
        if entry.get("not_found"):
            return " " + BROKEN_BADGE
        parts = []
        if entry.get("stars") is not None:
            parts.append(STARS_BADGE.format(format_stars(entry["stars"])))
        if entry.get("last_update"):
            parts.append(commit_badge(entry, meta))
        return (" " + " ".join(parts)) if parts else ""
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
                # Tags render only as footer bubbles (from front matter), so
                # the trailing tag tokens leave the entry text. Fenced example
                # bullets (docs) are left completely untouched.
                line = strip_trailing_tags(line)
            line = line.rstrip() + badge_suffix(line, meta)
        out_lines.append(line)
    return "\n".join(out_lines)


def page_tags(text):
    """Unique tags from inline backtick tokens on list-item lines.

    `type:tool`-style tokens contribute their value (tool); plain tokens
    (free, osint, ...) are kept raw. Feeds Zensical's native tags plugin so
    entries' tags are searchable and filterable at page level."""
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


# Nightshell theme: fonts are self-hosted from assets/fonts/ (variable woff2,
# latin subset, OFL-licensed); build copies that directory next to theme.css
# and theme.font=false disables Zensical's Google Fonts autoloading. Applied
# via the --md-text-font/--md-code-font variables so system fallback keeps
# working.
THEME_FACES = """@font-face { font-family: "Inter"; font-style: normal; font-weight: 400 700; font-display: swap; src: url("fonts/inter-latin-var.woff2") format("woff2"); }
@font-face { font-family: "JetBrains Mono"; font-style: normal; font-weight: 400 700; font-display: swap; src: url("fonts/jetbrains-mono-latin-var.woff2") format("woff2"); }
:root { --md-text-font: "Inter"; --md-code-font: "JetBrains Mono"; }
"""

THEME_CSS = THEME_FACES + """.md-typeset h1, .md-typeset h2, .md-typeset h3 { font-family: "JetBrains Mono", var(--md-text-font-family, sans-serif); letter-spacing: -0.02em; }
[data-md-color-scheme="slate"] { --md-default-bg-color: #0a0f14; --md-code-bg-color: #0d1520; --md-typeset-a-color: #34d399; }
.md-banner { background: #052e16; color: #6ee7b7; font-family: "JetBrains Mono", monospace; font-size: .75em; }
.hp-hero { background: linear-gradient(180deg, #020617, #052e16); border: 1px solid #10b98155; border-radius: 12px; padding: clamp(1.2rem, 5vw, 2.2rem) clamp(1rem, 5vw, 2rem); margin: 1.5rem 0; color: #d1fae5; }
.hp-hero .prompt { font-family: "JetBrains Mono", monospace; color: #34d399; font-size: .95rem; overflow-wrap: anywhere; }
.hp-hero .cursor::after { content: "\u258b"; animation: blink 1.1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.hp-hero h2 { color: #ecfdf5; margin: .6rem 0 .2rem; }
.hp-hero p { color: #a7f3d0; }
.hp-chips { margin-top: 1rem; display: flex; gap: .5rem; flex-wrap: wrap; }
.hp-chips span { font-family: "JetBrains Mono", monospace; font-size: .72rem; padding: .25rem .7rem; border-radius: 999px; background: #064e3b; color: #6ee7b7; border: 1px solid #10b98144; }
.md-tag { background: #022c22 !important; color: #6ee7b7 !important; border: 1px solid #10b98155; border-radius: 999px; font-family: "JetBrains Mono", monospace; }
[data-md-color-scheme="default"] .md-tag { background: #d1fae5 !important; color: #065f46 !important; border-color: #10b98155; }
a.md-tag { transition: transform .15s ease, box-shadow .15s ease, filter .15s ease; }
a.md-tag:hover { transform: translateY(-2px); box-shadow: 0 4px 14px #10b9813d !important; filter: brightness(1.12); }
a.md-tag:active { transform: translateY(0); box-shadow: 0 1px 4px #10b98133 !important; }
.md-content table { border-radius: 10px; overflow: auto; }
.md-content tbody tr:hover { background: #0596690f; }
.hp-badge { display: inline-block; font-family: "JetBrains Mono", monospace; font-size: .64rem; padding: .1rem .45rem; line-height: 1.4; border-radius: 999px; border: 1px solid transparent; white-space: nowrap; transition: transform .15s ease, box-shadow .15s ease; }
.hp-badge:hover { transform: translateY(-1px); box-shadow: 0 3px 10px #10b9813d; }
.hp-badge--stars { background: #78350f; color: #fde68a; border-color: #fbbf2466; }
[data-md-color-scheme="default"] .hp-badge--stars { background: #f59e0b; color: #292002; border-color: #fbbf2466; }
.hp-badge--commit { background: #022c22; color: #6ee7b7; border-color: #10b98155; }
[data-md-color-scheme="default"] .hp-badge--commit { background: #d1fae5; color: #065f46; border-color: #10b98155; }
.hp-badge--commit-active { background: #1a2e05; color: #a3e635; border-color: #84cc1655; }
[data-md-color-scheme="default"] .hp-badge--commit-active { background: #ecfccb; color: #3f6212; border-color: #84cc1655; }
.hp-badge--commit-aging { background: #451a03; color: #fcd34d; border-color: #f59e0b55; }
[data-md-color-scheme="default"] .hp-badge--commit-aging { background: #fef3c7; color: #92400e; border-color: #f59e0b55; }
.hp-badge--commit-dormant { background: #450a0a; color: #fca5a5; border-color: #ef444455; }
[data-md-color-scheme="default"] .hp-badge--commit-dormant { background: #fee2e2; color: #991b1b; border-color: #ef444455; }
.hp-badge--broken { background: #7f1d1d33; color: #fca5a5; border-color: #f8717155; }
[data-md-color-scheme="default"] .hp-badge--broken { background: #fee2e2; color: #991b1b; border-color: #ef444455; }
@media (max-width: 30em) { .hp-badge { font-size: .58rem; padding: .08rem .4rem; } }
@media (hover: none) { .hp-badge:hover { transform: none; box-shadow: none; } a.md-tag:hover { transform: none; box-shadow: none; } }
"""

HOME_HERO = """<div class="hp-hero">
  <div class="prompt">root@hackpot:~$ ./jackpot --catalog all <span class="cursor"></span></div>
  <h2>The jackpot of pentesting resources</h2>
  <p>Category-first, curated, CI-verified. Tools, courses, wordlists, labs and reading — across the whole kill chain.</p>
  <div class="hp-chips"><span>17 categories</span><span>weekly link checks</span><span>star &amp; freshness badges</span><span>search by name + tag</span></div>
</div>

"""

# The native tags plugin (adapted from Material's tags plugin) renders a
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
    # Self-hosted fonts and OFL license texts ship with the site.
    repo_fonts = ROOT / "assets" / "fonts"
    if repo_fonts.is_dir():
        shutil.copytree(repo_fonts, styles / "fonts", dirs_exist_ok=True)

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
        "  font: false",
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
