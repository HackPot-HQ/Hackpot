"""Generate the Hackpot GitHub Pages site from the README tree.

The READMEs are the single source of truth: this script mirrors them into
docs/ (git-ignored), rewrites relative links for Zensical, injects star and
freshness badges for GitHub repositories (from meta/resources-meta.json),
renders each entry's backtick tags as per-resource chips that filter the page
and link into a generated tag->resources hub (tags.md), and writes the site
configuration. Run by .github/workflows/deploy-docs.yml.
"""

import argparse
import html as htmlmod
import json
import pathlib
import posixpath
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
ENTRY_NAME_RE = re.compile(r"^(\s*[-*] )(?=\[)")
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


def transform(text, meta, repo_url, tagged=False, tags_href="", sink=None):
    out_lines = []
    in_fence = False
    used_anchors = set()
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
            if tagged:
                # Tags belong to their resource: the trailing token run leaves
                # the text and comes back as chips on the same entry, with a
                # stable anchor for the Tags hub to link into. Fenced example
                # bullets (docs) are left completely untouched.
                tags = entry_tags(line)
                if tags:
                    line = strip_trailing_tags(line)
                    prefix_m = ENTRY_NAME_RE.match(line)
                    prefix = prefix_m.group(1)
                    name_m = re.match(r"\[([^\]]+)\]", line[len(prefix):])
                    base = "e-" + slugify(name_m.group(1) if name_m else "entry")
                    anchor, n = base, 2
                    while anchor in used_anchors:
                        anchor = f"{base}-{n}"
                        n += 1
                    used_anchors.add(anchor)
                    line = (prefix + f'<a id="{anchor}"></a>' + line[len(prefix):])
                    if sink is not None:
                        sink.append((name_m.group(1) if name_m else "entry",
                                     anchor, tags))
                    line = line.rstrip() + badge_suffix(line, meta)
                    line = line + " " + tag_chips(tags, tags_href)
                    out_lines.append(line)
                    continue
            line = line.rstrip() + badge_suffix(line, meta)
        out_lines.append(line)
    return "\n".join(out_lines)


def slugify(value):
    """Anchor-safe slug: casefolded, runs of anything outside [a-z0-9_+-]
    become single hyphens, edge hyphens trimmed. Never empty."""
    slug = re.sub(r"[^a-z0-9_+-]+", "-", value.casefold()).strip("-")
    return slug or "entry"


def entry_tags(line):
    """(tag, is_type) pairs from the TRAILING backtick run of one entry line.

    `type:tool`-style tokens contribute their value (tool) flagged as type;
    plain tokens (osint, linux, ...) are kept raw. Unlike the removed page
    aggregation, inline code inside the description is never a tag — only
    the trailing run counts (CONTRIBUTING: tags are always last)."""
    if not LIST_ITEM_RE.match(line):
        return []
    run = TRAILING_TAGS_RE.search(line)
    if not run:
        return []
    pairs = []
    for token in TAG_TOKEN_RE.findall(run.group(0)):
        token = token.strip()
        is_type = token.startswith(TAG_TYPE_PREFIX)
        if is_type:
            token = token[len(TAG_TYPE_PREFIX):].strip()
        if token and (token, is_type) not in pairs:
            pairs.append((token, is_type))
    return pairs


def tag_chips(tags, tags_href):
    """Inline HTML: one clickable chip per tag, linking to the tag's section
    in the generated Tags hub."""
    chips = []
    for tag, is_type in tags:
        cls = "hp-tag hp-tag--type" if is_type else "hp-tag"
        escaped = htmlmod.escape(tag, quote=True)
        href = f"{tags_href}#t-{slugify(tag)}"
        chips.append(f'<a class="{cls}" data-tag="{escaped}" href="{href}">{escaped}</a>')
    return '<span class="hp-tags">' + "".join(chips) + "</span>"


def render_tags(index):
    """Tags hub page: every tag groups the resources it labels (tag->entries),
    each linking straight to its anchored entry on the category page."""
    lines = ["# Tags", "",
             "Every tag used across the catalog, grouped by the resources it",
             "labels. Each line links straight to that resource on its page;",
             "on a resource page, clicking a chip filters the list in place.",
             ""]
    used_ids = set()
    for tag in sorted(index, key=lambda t: t.casefold()):
        anchor = "t-" + slugify(tag)
        base, n = anchor, 2
        while anchor in used_ids:
            anchor = f"{base}-{n}"
            n += 1
        used_ids.add(anchor)
        lines.append(f'<a id="{anchor}"></a>')
        lines.append(f"## {tag}")
        lines.append("")
        for name, doc, entry_anchor, crumb in sorted(
                index[tag], key=lambda i: (i[0].casefold(), i[1], i[2])):
            lines.append(f"- [{name}]({doc}#{entry_anchor}) — {crumb}")
        lines.append("")
    return "\n".join(lines)


def convert(source, dest, meta, repo_url, tagged=False, sink=None, crumb=""):
    text = source.read_text(encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rel_dir = dest.parent.relative_to(DOCS).as_posix()
    tags_href = posixpath.relpath("tags.md", rel_dir if rel_dir != "." else ".")
    page_hits = []
    body = transform(text, meta, repo_url, tagged=tagged,
                     tags_href=tags_href, sink=page_hits)
    dest.write_text(body, encoding="utf-8")
    if sink is not None:
        doc = dest.relative_to(DOCS).as_posix()
        for name, entry_anchor, tags in page_hits:
            for tag, _is_type in tags:
                sink.setdefault(tag, []).append((name, doc, entry_anchor, crumb))
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
a.hp-tag { display: inline-block; font-family: "JetBrains Mono", monospace; font-size: .62rem; line-height: 1.5; padding: .06rem .5rem; margin: 0 .1rem; border-radius: 999px; background: transparent; color: #6ee7b7; border: 1px solid #10b98155; white-space: nowrap; transition: transform .15s ease, box-shadow .15s ease, filter .15s ease; }
a.hp-tag--type { background: #10b981; color: #022c22; font-weight: 700; border-color: #10b981; }
a.hp-tag--type::before { content: "\\25C6 "; font-size: .55rem; }
[data-md-color-scheme="default"] .hp-tag { background: transparent; color: #065f46; border-color: #10b98199; }
[data-md-color-scheme="default"] a.hp-tag--type { background: #10b981; color: #022c22; border-color: #10b981; }
a.hp-tag.on { background: #10b981; color: #022c22; font-weight: 700; border-color: #10b981; }
.hp-tags { display: inline; }
a.hp-tag:hover { transform: translateY(-2px); box-shadow: 0 4px 14px #10b9813d; filter: brightness(1.12); }
a.hp-tag:active { transform: translateY(0); box-shadow: 0 1px 4px #10b98133; }
.hp-filterbar { position: sticky; top: 2.6rem; z-index: 4; background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lightest); border-radius: 10px; padding: .55rem .8rem; margin: .6rem 0 1rem; }
.hp-filter-lbl { font-family: "JetBrains Mono", monospace; font-size: .7rem; color: var(--md-default-fg-color--light); text-transform: uppercase; margin-right: .5rem; }
.hp-filter-row { margin-top: .4rem; }
.hp-filter-count { font-family: "JetBrains Mono", monospace; font-size: .72rem; color: #fbbf24; }
.hp-filter-clear { font-family: "JetBrains Mono", monospace; font-size: .72rem; color: inherit; background: none; border: 1px solid #ef444455; border-radius: 999px; padding: .12rem .6rem; cursor: pointer; margin-left: .6rem; }
.hp-filter-index { font-family: "JetBrains Mono", monospace; font-size: .72rem; margin-left: .6rem; }
.md-content li.hp-hidden { display: none; }
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
@media (max-width: 30em) { .hp-badge { font-size: .58rem; padding: .08rem .4rem; } a.hp-tag { font-size: .58rem; padding: .05rem .4rem; } }
@media (hover: none) { .hp-badge:hover { transform: none; box-shadow: none; } a.hp-tag:hover { transform: none; box-shadow: none; } }
"""

HOME_HERO = """<div class="hp-hero">
  <div class="prompt">root@hackpot:~$ ./jackpot --catalog all <span class="cursor"></span></div>
  <h2>The jackpot of pentesting resources</h2>
  <p>Category-first, curated, CI-verified. Tools, courses, wordlists, labs and reading — across the whole kill chain.</p>
  <div class="hp-chips"><span>17 categories</span><span>weekly link checks</span><span>star &amp; freshness badges</span><span>search by name + tag</span></div>
</div>

"""

# Live per-resource filtering over the tag chips (S2). Progressive
# enhancement: without JS the chips stay plain links into the Tags hub.
TAGS_FILTER_JS = """/* Hackpot per-resource tags: click a chip to add/remove its tag in this
   page's live filter (AND semantics). Ctrl/Cmd/middle-click still follows the
   chip link into the whole-site Tags hub. Selection deep-links via
   #filter=tag+tag; without JS chips stay plain links and nothing is hidden. */
(function () {
  "use strict";
  var content = document.querySelector(".md-content .md-typeset")
    || document.querySelector(".md-content");
  if (!content) return;
  var groups = [];
  content.querySelectorAll("ul, ol").forEach(function (ul) {
    var items = [].filter.call(ul.children, function (el) {
      return el.tagName === "LI" && el.querySelector(".hp-tags a.hp-tag");
    });
    if (items.length) groups.push({ ul: ul, items: items });
  });
  if (!groups.length) return;

  var counts = {}, allItems = [];
  groups.forEach(function (g) {
    g.items.forEach(function (li) {
      allItems.push(li);
      li.querySelectorAll(".hp-tags a.hp-tag").forEach(function (a) {
        var t = a.getAttribute("data-tag");
        counts[t] = (counts[t] || 0) + 1;
      });
    });
  });
  var tags = Object.keys(counts).sort(function (a, b) {
    return counts[b] - counts[a] || a.localeCompare(b);
  });
  var TYPE = ["tool", "docs", "lab", "article", "video", "course", "wordlist"];
  var sel = [];

  var bar = document.createElement("div");
  bar.className = "hp-filterbar";
  bar.innerHTML =
    '<span class="hp-filter-lbl">Filter</span><span class="hp-filter-chips"></span>'
    + '<div class="hp-filter-row"><span class="hp-filter-count"></span>'
    + '<button class="hp-filter-clear" type="button">clear \u2715</button>'
    + '<a class="hp-filter-index" href="#">Tags index \u2192</a></div>';
  groups[0].ul.parentNode.insertBefore(bar, groups[0].ul);

  var firstChip = allItems[0].querySelector(".hp-tags a.hp-tag");
  bar.querySelector(".hp-filter-index").href =
    firstChip.getAttribute("href").split("#")[0];

  function renderBar() {
    var wrap = bar.querySelector(".hp-filter-chips");
    wrap.innerHTML = "";
    tags.forEach(function (t) {
      var a = document.createElement("a");
      a.className = "hp-tag" + (TYPE.indexOf(t) >= 0 ? " hp-tag--type" : "")
        + (sel.indexOf(t) >= 0 ? " on" : "");
      a.href = "#";
      a.setAttribute("data-tag", t);
      a.textContent = t + " " + counts[t];
      wrap.appendChild(a);
    });
  }
  function updateUrl() {
    var base = location.href.split("#")[0];
    history.replaceState(null, "",
      base + (sel.length ? "#filter=" + sel.map(encodeURIComponent).join("+") : ""));
  }
  function apply() {
    renderBar();
    var shown = 0;
    allItems.forEach(function (li) {
      var chips = [].slice.call(li.querySelectorAll(".hp-tags a.hp-tag"));
      var liTags = chips.map(function (a) { return a.getAttribute("data-tag"); });
      var ok = sel.every(function (t) { return liTags.indexOf(t) >= 0; });
      li.classList.toggle("hp-hidden", !ok);
      if (ok) shown++;
      chips.forEach(function (a) {
        a.classList.toggle("on", sel.indexOf(a.getAttribute("data-tag")) >= 0);
      });
    });
    bar.querySelector(".hp-filter-count").textContent =
      shown + " / " + allItems.length + " resources";
    updateUrl();
  }
  function toggle(t) {
    var i = sel.indexOf(t);
    if (i >= 0) { sel.splice(i, 1); } else { sel.push(t); }
    apply();
  }
  content.addEventListener("click", function (e) {
    var chip = e.target.closest ? e.target.closest("a.hp-tag") : null;
    if (!chip) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    toggle(chip.getAttribute("data-tag"));
  });
  bar.querySelector(".hp-filter-clear").addEventListener("click", function () {
    sel = [];
    apply();
  });
  var m = location.hash.match(/^#filter=(.*)$/);
  if (m) {
    m[1].split("+").forEach(function (t) {
      t = decodeURIComponent(t);
      if (counts[t] && sel.indexOf(t) < 0) sel.push(t);
    });
  }
  apply();
})();
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
    nav.append(("Tags", "tags.md"))

    tag_index = {}
    category_pages = []
    for category_dir in sorted(
        p for p in ROOT.iterdir() if p.is_dir() and CATEGORY_DIR_RE.match(p.name)
    ):
        cat_title = page_title(category_dir / "README.md")
        cat_crumb = f"{category_dir.name[:2]} · {cat_title}"
        cat_nav = []
        cat_file = f"{category_dir.name}/index.md"
        convert(category_dir / "README.md", DOCS / cat_file, meta, repo_url,
                tagged=True, sink=tag_index, crumb=cat_crumb)
        cat_nav.append(("Overview", cat_file))
        for leaf_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            leaf_title = page_title(leaf_dir / "README.md")
            leaf_file = f"{category_dir.name}/{leaf_dir.name}/index.md"
            convert(leaf_dir / "README.md", DOCS / leaf_file, meta, repo_url,
                    tagged=True, sink=tag_index, crumb=f"{cat_crumb} / {leaf_title}")
            cat_nav.append((leaf_title, leaf_file))
        category_pages.append((cat_crumb, cat_nav))
    nav.extend(category_pages)
    (DOCS / "tags.md").write_text(render_tags(tag_index), encoding="utf-8")

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
    scripts_dir = DOCS / "javascripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "tags-filter.js").write_text(TAGS_FILTER_JS, encoding="utf-8")
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
        "extra_javascript:",
        "  - \"javascripts/tags-filter.js\"",
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
