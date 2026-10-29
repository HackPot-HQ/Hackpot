"""Regression tests for scripts/build_site.py."""

import pathlib
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_site  # noqa: E402


_BUILD_CACHE = []


def cached_build():
    """One generated tree shared by the config/tag suites, cleaned on exit."""
    if not _BUILD_CACHE:
        tmp = tempfile.mkdtemp(prefix="hackpot_build_site_")
        out = pathlib.Path(tmp) / "docs"
        build_site.build(out, repo_url="https://github.com/HackPot-HQ/Hackpot")
        _BUILD_CACHE.append((tmp, out))
        import atexit
        atexit.register(lambda: [shutil.rmtree(t, ignore_errors=True) for t, _ in _BUILD_CACHE])
    return _BUILD_CACHE[0][1]


class EmittedConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()
        # Zensical requires site_dir within the project root (= config dir),
        # so build_site.py emits the config next to docs/, not inside it.
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_uses_zensical_variant_not_material_name(self):
        # Zensical replaces Material; variant classic keeps the current look.
        self.assertIn('variant: "classic"', self.yml)
        self.assertNotIn('name: "material"', self.yml)

    def test_site_dir_in_config(self):
        # Zensical has no --site-dir, so site_dir must live in config,
        # within the project root.
        self.assertIn('site_dir: "site"', self.yml)
        self.assertIn('docs_dir: "docs"', self.yml)

    def test_search_plugin_and_tags_filter_script(self):
        # S1/S2: the native tags plugin is dropped (no more page-level bubbles);
        # the tag hub is generator-authored and filtering ships as a script.
        self.assertRegex(self.yml, r"(?m)^\s*-\s*\"?search\"?\s*$")
        self.assertNotRegex(self.yml, r"(?m)^\s*-\s*\"?tags\"?\s*$")
        self.assertIn("extra_javascript:", self.yml)
        self.assertIn('"javascripts/tags-filter.js"', self.yml)

    def test_search_highlight_feature(self):
        self.assertIn('"search.highlight"', self.yml)

    def test_palette_emits_auto_light_dark_toggle(self):
        # Dark and light themes with automatic system-preference mode.
        for needle in (
            'scheme: "default"',
            'scheme: "slate"',
            'media: "(prefers-color-scheme)"',
            'icon: "lucide/sun"',
            'icon: "lucide/moon"',
        ):
            self.assertIn(needle, self.yml)


class EntryTags(unittest.TestCase):
    # S3/S4: tags belong to one resource, not to the page.

    def test_controlled_entry_tag_extraction(self):
        # Hermetic unit: type: stripping (incl. a space after the prefix),
        # dedupe, whitespace, empty values, and — unlike the old page-level
        # aggregation — ONLY the trailing run counts (inline code like
        # `nmap` in a description is not a tag).
        cases = (
            ("- [A](u) — a. `type:tool` ` linux ` `dup` `dup`",
             [("tool", True), ("linux", False), ("dup", False)]),
            ("- [B](u) — b. `type:` `type: spaced`", [("spaced", True)]),
            ("- [C](u) — uses `nmap` scripts. `linux`", [("linux", False)]),
            ("- [D](u) — no tags at all", []),
            ("Not a list item: `ignored`", []),
        )
        for src, want in cases:
            self.assertEqual(build_site.entry_tags(src), want, src)

    def test_tagged_transform_emits_anchor_and_chips_exactly(self):
        out = build_site.transform(
            "- [X](https://x.test) — does things. `type:tool` `linux`\n",
            {}, None, tagged=True, tags_href="../../tags.md")
        self.assertEqual(
            out,
            '- <a id="e-x"></a>[X](https://x.test) — does things.'
            ' <span class="hp-tags">'
            '<a class="hp-tag hp-tag--type" data-tag="tool"'
            ' href="../../tags.md#t-tool">tool</a>'
            '<a class="hp-tag" data-tag="linux"'
            ' href="../../tags.md#t-linux">linux</a></span>\n')

    def test_untagged_transform_unchanged_old_contract(self):
        # S5: home/contributing keep literal tokens as source documentation.
        src = "- [X](https://x.test) — does things. `type:tool` `linux`\n"
        self.assertEqual(build_site.transform(src, {}, None), src)

    def test_duplicate_names_get_unique_anchors(self):
        src = ("- [Same Name](https://x.test/1) — one. `x`\n"
               "- [Same Name](https://x.test/2) — two. `x`\n")
        out = build_site.transform(src, {}, None, tagged=True, tags_href="tags.md")
        self.assertIn('<a id="e-same-name"></a>', out)
        self.assertIn('<a id="e-same-name-2"></a>', out)

    def test_tagged_transform_keeps_inline_code_and_drops_tokens(self):
        src = "- [X](https://x.test) — uses `nmap` scripts. `type:tool` `linux`\n"
        out = build_site.transform(src, {}, None, tagged=True, tags_href="tags.md")
        self.assertIn("uses `nmap` scripts.", out)
        self.assertNotIn("`linux`", out)

    def test_sink_collects_per_entry_tag_index(self):
        sink = []
        build_site.transform(
            "- [9Ghz](https://9ghz.com/) — x. `type:tool` `breach`\n",
            {}, None, tagged=True, tags_href="tags.md", sink=sink)
        self.assertEqual(sink, [("9Ghz", "e-9ghz", [("tool", True), ("breach", False)])])

    def test_adjacent_inline_code_pins_current_semantics(self):
        # Advisory (verifier, 2026-10-29): a token directly abutting the
        # trailing run is captured — same-or-worse at baseline b31023b, where
        # page_tags scanned the whole line. Pinned so a future change to this
        # boundary is a deliberate decision, not an accident.
        self.assertEqual(
            build_site.entry_tags("- [N](u) — runs `nmap` `tool`"),
            [("nmap", False), ("tool", False)])

    def test_tags_page_renders_resources_grouped_by_tag(self):
        hub = build_site.render_tags({
            "breach": [("9Ghz", "01_Recon_and_OSINT/OSINT/index.md", "e-9ghz",
                        "01 · Recon and OSINT / OSINT")],
            "tool": [("9Ghz", "01_Recon_and_OSINT/OSINT/index.md", "e-9ghz",
                      "01 · Recon and OSINT / OSINT")],
        })
        self.assertTrue(hub.startswith("# Tags"))
        self.assertIn('<a id="t-breach"></a>\n## breach\n', hub)
        self.assertIn("- [9Ghz](01_Recon_and_OSINT/OSINT/index.md#e-9ghz) — "
                      "01 · Recon and OSINT / OSINT", hub)
        # sections sorted case-insensitively by tag
        self.assertLess(hub.index("t-breach"), hub.index("t-tool"))

    def test_home_and_contributing_have_no_front_matter(self):
        docs = cached_build()
        for name in ("index.md", "contributing.md"):
            p = docs / name
            self.assertTrue(p.exists(), f"generator stopped emitting {name}")
            self.assertFalse(p.read_text(encoding="utf-8").startswith("---\n"))


class Badges(unittest.TestCase):
    def test_not_found_uses_literal_emoji(self):
        # No Material emoji shortcodes (:warning:) — Zensical must render
        # the warning without emoji-extension config.
        meta = {"repos": {"owner/repo": {"not_found": True}}}
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertIn("\u26a0\ufe0f", suffix)
        self.assertNotIn(":warning:", suffix)

    def test_commit_pill_shows_age_and_tier_against_checked_at(self):
        # Stars pill in solid amber; commit pill shows age (not the date)
        # and Option A traffic-light tier vs meta checked_at: 26d -> fresh.
        meta = {
            "checked_at": "2026-10-27T09:55:49Z",
            "repos": {"owner/repo": {"stars": 12000, "last_update": "2026-10-01"}},
        }
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(
            suffix,
            ' <span class="hp-badge hp-badge--stars">★ 12.0k</span>'
            ' <span class="hp-badge hp-badge--commit hp-badge--commit-fresh">'
            'last commit 26d</span>')

    def test_commit_tier_boundaries(self):
        # Option A: fresh <=30d, active 31-180d, aging 181-365d, dormant >365d.
        for days, tier in (
            (0, "fresh"), (29, "fresh"), (30, "fresh"),
            (31, "active"), (180, "active"),
            (181, "aging"), (365, "aging"),
            (366, "dormant"), (4000, "dormant"),
        ):
            self.assertEqual(build_site.commit_tier(days), tier, f"{days}d")

    def test_format_age_switches_to_years_past_a_year(self):
        # < 365d -> "Nd"; >= 365d -> "Yy Dd" on a 365-day year; bare "Yy"
        # when the remainder is 0.
        self.assertEqual(build_site.format_age(0), "0d")
        self.assertEqual(build_site.format_age(364), "364d")
        self.assertEqual(build_site.format_age(365), "1y")
        self.assertEqual(build_site.format_age(400), "1y 35d")
        self.assertEqual(build_site.format_age(730), "2y")
        self.assertEqual(build_site.format_age(2022), "5y 197d")

    def test_dormant_pill_formats_years(self):
        meta = {
            "checked_at": "2026-10-27T09:55:49Z",
            "repos": {"owner/repo": {"last_update": "2024-10-27"}},
        }
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(
            suffix,
            ' <span class="hp-badge hp-badge--commit hp-badge--commit-dormant">'
            'last commit 2y</span>')

    def test_aging_pill_uses_amber_tier(self):
        meta = {
            "checked_at": "2026-10-27",
            "repos": {"owner/repo": {"last_update": "2026-01-01"}},
        }
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(
            suffix,
            ' <span class="hp-badge hp-badge--commit hp-badge--commit-aging">'
            'last commit 299d</span>')

    def test_future_update_clamps_to_fresh_zero_days(self):
        # Clock skew must never render "last commit -3d".
        meta = {
            "checked_at": "2026-10-27",
            "repos": {"owner/repo": {"last_update": "2026-10-30"}},
        }
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertIn("hp-badge--commit-fresh", suffix)
        self.assertIn("last commit 0d", suffix)

    def test_date_display_converts_iso_to_ddmm(self):
        # Storage stays ISO (YYYY-MM-DD); the fallback (no checked_at) and any
        # unparsable stamp keep the DD-MM-YYYY rendering.
        self.assertEqual(build_site.format_date("2026-10-01"), "01-10-2026")
        self.assertEqual(build_site.format_date("2021-04-15"), "15-04-2021")
        self.assertEqual(build_site.format_date("garbage"), "garbage")
        self.assertEqual(build_site.format_date(None), "")

    def test_no_stars_pill_when_stars_missing(self):
        # Differential pin: with no checked_at reference the commit pill keeps
        # its previous absolute-date output and base palette.
        meta = {"repos": {"owner/repo": {"stars": None, "last_update": "2026-10-01"}}}
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(
            suffix,
            ' <span class="hp-badge hp-badge--commit">last commit 01-10-2026</span>')

    def test_entry_lines_survive_transform(self):
        # Differential pin: content pages must keep their entry bullets.
        src = "# T\n\n- [HackBar](https://github.com/d3vilbug/HackBar) — x. `type:tool` `linux`\n"
        out = build_site.transform(src, {}, "https://github.com/HackPot-HQ/Hackpot")
        self.assertIn("- [HackBar](https://github.com/d3vilbug/HackBar)", out)
        self.assertIn("`type:tool`", out)


class NightshellTheme(unittest.TestCase):
    # The "Nightshell" theme is what the generator must emit.
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_palette_custom_emerald_schemes(self):
        self.assertIn('primary: "#047857"', self.yml)
        self.assertIn('accent: "#10b981"', self.yml)
        self.assertIn('primary: "#022c22"', self.yml)
        self.assertIn('accent: "#34d399"', self.yml)

    def test_extra_css_and_theme_file_emitted(self):
        self.assertIn("extra_css:", self.yml)
        self.assertIn('"stylesheets/theme.css"', self.yml)
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn('@font-face', css)
        self.assertIn('url("fonts/inter-latin-var.woff2")', css)
        self.assertIn('url("fonts/jetbrains-mono-latin-var.woff2")', css)
        self.assertIn(".hp-hero", css)
        # "Soft Lift" hover style, now on the per-entry tag chips (S6).
        self.assertIn("a.hp-tag:hover { transform: translateY(-2px)", css)
        self.assertIn("a.hp-tag {", css)
        self.assertIn("a.hp-tag:active", css)
        # Bubbles are gone: the plugin's md-tag styling must not linger.
        self.assertNotIn("md-tag", css)
        # Fonts are hosted in the repo: no CDN.
        self.assertNotIn("fonts.googleapis.com", css)
        self.assertNotIn("fonts.gstatic.com", css)
        self.assertIn("font: false", self.yml)  # stops Google Fonts autoloading
        self.assertIn('--md-text-font: "Inter"', css)
        self.assertIn('--md-code-font: "JetBrains Mono"', css)
        # The yellow stars pill and emerald commit pill must ship in the CSS,
        # including a light-scheme variant for the amber pill.
        self.assertIn(".hp-badge--stars { background: #78350f; color: #fde68a;", css)
        self.assertIn('[data-md-color-scheme="default"] .hp-badge--stars', css)
        self.assertIn(".hp-badge--commit", css)
        self.assertIn(".hp-badge--broken", css)

    def test_commit_tier_palettes_ship_in_css(self):
        # Option A traffic light: active/aging/dormant override the emerald
        # base, each with a light-scheme variant, and they must come AFTER the
        # base .hp-badge--commit rules so the cascade wins on equal specificity.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        for needle in (
            ".hp-badge--commit-active { background: #1a2e05; color: #a3e635;",
            '[data-md-color-scheme="default"] .hp-badge--commit-active '
            '{ background: #ecfccb; color: #3f6212;',
            ".hp-badge--commit-aging { background: #451a03; color: #fcd34d;",
            '[data-md-color-scheme="default"] .hp-badge--commit-aging '
            '{ background: #fef3c7; color: #92400e;',
            ".hp-badge--commit-dormant { background: #450a0a; color: #fca5a5;",
            '[data-md-color-scheme="default"] .hp-badge--commit-dormant '
            '{ background: #fee2e2; color: #991b1b;',
        ):
            self.assertIn(needle, css)
        self.assertLess(css.index(".hp-badge--commit {"), css.index(".hp-badge--commit-active {"))
        self.assertLess(css.index('[data-md-color-scheme="default"] .hp-badge--commit {'),
                        css.index('[data-md-color-scheme="default"] .hp-badge--commit-active {'))

    def test_pills_scale_down_on_mobile(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # Compact base pill: smaller font and tighter padding so the stars /
        # last-commit chips never crowd or overlap the entry text.
        self.assertIn("font-size: .64rem; padding: .1rem .45rem;", css)
        self.assertIn("line-height: 1.4;", css)
        # Phone-width screens scale the pills down even further.
        self.assertIn("@media (max-width: 30em) { .hp-badge { font-size: .58rem;", css)
        # Touch devices must not keep the translateY lift hover, which sticks
        # after a tap and makes pills ride over the surrounding text.
        self.assertIn("@media (hover: none) { .hp-badge:hover { transform: none;", css)

    def test_tag_chips_no_sticky_hover_on_touch(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # Chips lift -2px on hover; on touch that lift sticks after a tap, so
        # the guard must cover them the same way it covers pills.
        self.assertIn(
            "@media (hover: none) { .hp-badge:hover { transform: none; "
            "box-shadow: none; } a.hp-tag:hover { transform: none; box-shadow: none; } }",
            css)

    def test_chip_and_filterbar_palette_ships(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # User pick (2026-10-29): POC4 style E "Outline" — border-only chips,
        # type value filled emerald as the single loud element. Cascade order
        # matters: each fill rule must come after the rule it overrides.
        self.assertIn("a.hp-tag {", css)
        self.assertIn("background: transparent; color: #6ee7b7; border: 1px solid #10b98155;", css)
        self.assertIn('a.hp-tag--type { background: #10b981; color: #022c22; font-weight: 700;', css)
        self.assertIn('[data-md-color-scheme="default"] .hp-tag { background: transparent;', css)
        self.assertIn('[data-md-color-scheme="default"] a.hp-tag--type { background: #10b981;', css)
        self.assertLess(css.index("a.hp-tag {"), css.index("a.hp-tag--type {"))
        self.assertLess(css.index('[data-md-color-scheme="default"] .hp-tag {'),
                        css.index('[data-md-color-scheme="default"] a.hp-tag--type {'))
        # Filter toolbar on-state still paints after every base/light rule.
        self.assertLess(css.index('[data-md-color-scheme="default"] a.hp-tag--type'),
                        css.index(".hp-tag.on"))
        self.assertIn(".hp-tag.on", css)
        # Selected chips must be unmistakable even when the fill already is
        # the accent (type chips under the outline style): a check glyph is
        # appended to every on-state chip, toolbar and inline alike.
        self.assertIn('a.hp-tag.on::after { content: " \\2713"; font-weight: 700; }', css)
        self.assertIn(".hp-filterbar", css)

    def test_hero_padding_is_fluid(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # Fixed 2.2rem/2rem padding eats ~64px of a 360px phone screen; the
        # hero must clamp between a mobile floor and the desktop value.
        self.assertIn(
            "padding: clamp(1.2rem, 5vw, 2.2rem) clamp(1rem, 5vw, 2rem);", css)
        # The monospace prompt line must wrap instead of touching the edges.
        self.assertIn(
            ".hp-hero .prompt { font-family: \"JetBrains Mono\", monospace; "
            "color: #34d399; font-size: .95rem; overflow-wrap: anywhere; }", css)

    def test_tables_scroll_on_small_screens(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # overflow: hidden clips wide tables on mobile; auto keeps the
        # rounded corners and makes them swipeable instead.
        self.assertIn(".md-content table { border-radius: 10px; overflow: auto; }", css)

    def test_self_hosted_fonts_ship_with_the_site(self):
        for name in ("inter-latin-var.woff2", "jetbrains-mono-latin-var.woff2"):
            shipped = self.docs / "stylesheets" / "fonts" / name
            source = build_site.ROOT / "assets" / "fonts" / name
            self.assertTrue(source.is_file() and source.stat().st_size > 10_000,
                            f"repo font asset missing: {name}")
            self.assertEqual(shipped.read_bytes()[:4], b"wOF2", f"bad woff2: {name}")
        for license_name in ("LICENSE-inter.txt", "LICENSE-jetbrains-mono.txt"):
            text = (self.docs / "stylesheets" / "fonts" / license_name).read_text(encoding="utf-8")
            self.assertIn("SIL Open Font License", text)

    def test_home_hero_injected_before_categories(self):
        home = (self.docs / "index.md").read_text(encoding="utf-8")
        self.assertIn("hp-hero", home)
        self.assertIn("./jackpot --catalog all", home)
        self.assertLess(home.index("hp-hero"), home.index("## Categories"))

    def test_tags_hub_page_generated_and_in_nav(self):
        # S1: the hub is generator-authored (tag -> resources), not the plugin
        # marker anymore.
        hub = (self.docs / "tags.md").read_text(encoding="utf-8")
        self.assertTrue(hub.startswith("# Tags"))
        self.assertNotIn("<!-- material/tags -->", hub)
        self.assertIn('"Tags": "tags.md"', self.yml)
        # Real catalog data drives the index (breach comes from 9Ghz/HIBP).
        self.assertIn('<a id="t-breach"></a>', hub)
        self.assertIn("[9Ghz](01_Recon_and_OSINT/OSINT/index.md#e-9ghz)", hub)
        self.assertIn("[Have I Been Pwned]"
                      "(01_Recon_and_OSINT/OSINT/index.md#e-have-i-been-pwned)", hub)
        self.assertIn("01 · Reconnaissance and OSINT / OSINT", hub)

    def test_tags_filter_js_shipped(self):
        # S2: the live filter script is generated next to the theme assets.
        js = (self.docs / "javascripts" / "tags-filter.js").read_text(encoding="utf-8")
        for needle in ("hp-tag", "hp-tags", "hp-filterbar", "filter="):
            self.assertIn(needle, js)


class TagPerResource(unittest.TestCase):
    # S3/S4: entry pages show tags inside each entry line (chips), never as
    # page front matter or raw residue tokens.
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()

    def test_generated_tagged_pages_have_chips_not_raw_tokens(self):
        checked = 0
        for p in self.docs.rglob("index.md"):
            if p.parent == self.docs:
                continue
            text = p.read_text(encoding="utf-8")
            self.assertFalse(text.startswith("---\n"), f"front matter on {p}")
            if "hp-tag" in text:
                checked += 1
        self.assertGreaterEqual(checked, 1, "expected at least one page with chips")
        leaf = self.docs / "08_Web_Application" / "Vulnerability_Specific" / "index.md"
        leaf_text = leaf.read_text(encoding="utf-8")
        # entry bullets survive (names stay searchable) and carry their chips
        self.assertIn("[HackBar]", leaf_text)
        self.assertIn('<a id="e-hackbar"></a>', leaf_text)
        self.assertIn('data-tag="burp"', leaf_text)
        self.assertIn('href="../../tags.md#t-burp"', leaf_text)
        self.assertNotIn("`type:tool`", leaf_text)
        self.assertNotIn("`burp`", leaf_text)

    def test_hub_links_resolve_to_entry_anchors(self):
        # S1 end-to-end: every resource link in the generated hub must point
        # at an anchor that actually exists in the linked generated page.
        hub = (self.docs / "tags.md").read_text(encoding="utf-8")
        links = re.findall(r"^- \[[^\]]+\]\(([^)]+)\)", hub, re.M)
        self.assertGreaterEqual(len(links), 6, "hub unexpectedly empty")
        for target in links:
            path, frag = target.split("#", 1)
            page = (self.docs / path).read_text(encoding="utf-8")
            self.assertIn(f'<a id="{frag}"></a>', page, f"{target} dangling")

    def test_chip_hrefs_target_existing_hub_anchors(self):
        # S1/S2: every chip's #t-... href must exist on the hub.
        hub = (self.docs / "tags.md").read_text(encoding="utf-8")
        for p in self.docs.rglob("*.md"):
            for frag in set(re.findall(r'href="[^"]*#(t-[^"]+)"',
                                       p.read_text(encoding="utf-8"))):
                self.assertIn(f'id="{frag}"', hub, f"{p.name} -> {frag}")

    def test_contributing_example_stays_literal(self):
        # S5: contributor docs keep the raw token format they teach.
        text = (self.docs / "contributing.md").read_text(encoding="utf-8")
        self.assertIn("- [Name](https://canonical-url) — What it does and why "
                      "it matters. `type:tool` `linux`", text)
        self.assertNotIn("hp-tag", text)

    def test_fenced_example_bullets_are_untouched(self):
        # Doc examples inside ``` fences keep their literal tag tokens.
        src = (
            "- [X](https://x.test) — real entry. `linux`\n\n"
            "```markdown\n"
            "- [Name](https://example.com) — what it does. `type:tool` `linux`\n"
            "```\n"
        )
        out = build_site.transform(src, {}, None, tagged=True, tags_href="tags.md")
        self.assertIn(
            "- [Name](https://example.com) — what it does. `type:tool` `linux`", out)
        self.assertIn('- <a id="e-x"></a>[X](https://x.test) — real entry.', out)


if __name__ == "__main__":
    unittest.main()
