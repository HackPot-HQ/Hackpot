"""Regression tests for scripts/build_site.py."""

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date

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

    def test_badge_line_comes_before_the_tags_line(self):
        # User pick (2026-11-06): the stars/last-commit pills get their own
        # line like the tags, rendered BEFORE the tags line. Markup order is
        # the render order of the two block lines, so the badges span must
        # precede the chips span inside the entry bullet.
        meta = {"checked_at": "2026-10-27",
                "repos": {"owner/repo": {"stars": 500,
                                         "last_update": "2026-10-01"}}}
        out = build_site.transform(
            "- [X](https://github.com/owner/repo) — does things. `linux`\n",
            meta, None, tagged=True, tags_href="tags.md")
        self.assertIn('class="hp-badges"', out)
        self.assertLess(out.index('class="hp-badges"'),
                        out.index('class="hp-tags"'))

    def test_tag_chips_type_first_then_alphabetical(self):
        # Website requirement: chips show every tag of the resource sorted
        # alphabetically, with the type tag always first regardless of the
        # order the tokens appear in the source line.
        out = build_site.transform(
            "- [X](https://x.test) — does things. `zebra` `linux` "
            "`type:tool` `Apple`\n",
            {}, None, tagged=True, tags_href="../../tags.md")
        order = [m.group(1) for m in re.finditer(r'data-tag="([^"]+)"', out)]
        self.assertEqual(order, ["tool", "Apple", "linux", "zebra"])

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
        self.assertEqual(sink, [("9Ghz", "e-9ghz", [("tool", True), ("breach", False)],
                                "x.")])

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
                        "Check if you are in any data breach.")],
            "tool": [("9Ghz", "01_Recon_and_OSINT/OSINT/index.md", "e-9ghz",
                      "Check if you are in any data breach.")],
        })
        self.assertTrue(hub.startswith("# Tags"))
        self.assertIn('<a id="t-breach"></a>\n## breach\n', hub)
        # the resource line shows its description, not the category path
        self.assertIn('- [9Ghz](01_Recon_and_OSINT/OSINT/index.md#e-9ghz) — '
                      'Check if you are in any data breach.', hub)
        self.assertNotIn("class=\"where\"", hub)
        self.assertNotIn("01 ·", hub)
        # sections sorted case-insensitively by tag
        self.assertLess(hub.index("t-breach"), hub.index("t-tool"))

    def test_tags_sections_show_per_tag_resource_counts(self):
        # No top cloud (removed by user feedback 2026-11-05): the hub starts
        # straight at the sections, each headed by its resource count.
        hub = build_site.render_tags({
            "breach": [("9Ghz", "01_Recon_and_OSINT/OSINT/index.md", "e-9ghz",
                        "01 · Recon and OSINT / OSINT")],
            "osint": [("9Ghz", "01_Recon_and_OSINT/OSINT/index.md", "e-9ghz",
                       "01 · Recon and OSINT / OSINT"),
                      ("theHarvester", "01_Recon_and_OSINT/OSINT/index.md",
                       "e-theharvester", "01 · Recon and OSINT / OSINT")],
        })
        self.assertNotIn("hp-cloud", hub)
        self.assertEqual(hub.index("<a id="), hub.index('<a id="t-breach"'),
                         "sections must start right after the intro")
        self.assertIn('<a id="t-breach"></a>\n## breach\n\n'
                      '<p class="hp-tagcount">1 resource</p>', hub)
        self.assertIn('<a id="t-osint"></a>\n## osint\n\n'
                      '<p class="hp-tagcount">2 resources</p>', hub)

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
            ' <span class="hp-badges">'
            '<span class="hp-badge hp-badge--stars">★ 12.0k</span>'
            ' <span class="hp-badge hp-badge--commit hp-badge--commit-fresh">'
            'last commit 26d</span></span>')

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
            ' <span class="hp-badges">'
            '<span class="hp-badge hp-badge--commit hp-badge--commit-dormant">'
            'last commit 2y</span></span>')

    def test_aging_pill_uses_amber_tier(self):
        meta = {
            "checked_at": "2026-10-27",
            "repos": {"owner/repo": {"last_update": "2026-01-01"}},
        }
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(
            suffix,
            ' <span class="hp-badges">'
            '<span class="hp-badge hp-badge--commit hp-badge--commit-aging">'
            'last commit 299d</span></span>')

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
            ' <span class="hp-badges">'
            '<span class="hp-badge hp-badge--commit">last commit 01-10-2026</span></span>')

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

    def test_filterbar_does_not_float_over_content(self):
        # User pick (2026-11-06): the toolbar scrolls with the page; it must
        # never stay pinned on top of the list once the user scrolls past it.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        rule = re.search(r"\.hp-filterbar \{([^}]*)\}", css).group(1)
        self.assertNotIn("sticky", rule)
        self.assertNotIn("fixed", rule)

    def test_filterbar_is_collapsible_and_collapsed_by_default(self):
        # User pick (2026-11-06): the chips hide behind a summary line by
        # default; only a #filter= deep link (an active selection) opens it.
        js = (self.docs / "javascripts" / "tags-filter.js").read_text(encoding="utf-8")
        self.assertIn('document.createElement("details")', js)
        self.assertIn('<summary class="hp-filter-head">', js)
        self.assertRegex(js, r"if \(sel\.length\) bar\.open = true;")
        # Nothing may pre-open the bar outside that guarded deep-link case.
        self.assertEqual(js.count("bar.open = true"), 1)
        self.assertNotIn("setAttribute(\"open\"", js)
        # The clear button lives in the summary: a click there must not
        # double as a collapse toggle.
        self.assertRegex(js, r'\.hp-filter-clear"\)\.addEventListener\("click", function \(e\) \{\s*\n\s*e\.preventDefault\(\);')
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # Zensical restyles EVERY .md-typeset details/summary as a "note"
        # admonition (blue pencil ::before, chevron ::after, blue background,
        # absolute positioning, focus glow). Our rules must out-specify
        # "[dir=ltr] .md-typeset summary::before" (0,2,2) or the pencil wins.
        self.assertIn(
            ".md-typeset .hp-filterbar > summary.hp-filter-head::before", css)
        self.assertIn(
            ".md-typeset .hp-filterbar > summary.hp-filter-head::after { content: none; }", css)
        self.assertIn(
            ".md-typeset .hp-filterbar:focus-within { box-shadow: none; }", css)
        self.assertIn(".md-typeset .hp-filterbar[open] > summary.hp-filter-head::before", css)
        # User pick (2026-11-06): the marker is a funnel SVG painted through a
        # CSS mask (font-independent), not the old triangle glyph.
        self.assertIn("data:image/svg+xml,%3Csvg", css)
        self.assertIn("M2 3h20l-8 9v6l-4 2v-8z", css)
        # No triangle glyph may sneak back: neither as a proper CSS escape
        # nor as the Python octal-escape control char that shipped as the
        # "pencil" (chr(0o25) — the real bug behind the user report).
        self.assertNotIn('content: "\\25B8"', css)
        self.assertNotIn('content: "\\25BE"', css)
        self.assertNotIn("\x15", css)

    def test_filterbar_collapsed_text_is_optically_centered(self):
        # User pick (2026-11-06): the collapsed row must sit centered in the
        # bar on every engine: the summary hugs the ink (line-height 1.2,
        # not the inherited 1.6 leading) and the bar padding stays symmetric.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        bar = re.search(r"\.md-typeset \.hp-filterbar \{([^}]*)\}", css).group(1)
        self.assertIn("padding: .65rem .8rem;", bar)
        head = re.search(r"\.md-typeset \.hp-filterbar > summary\.hp-filter-head \{([^}]*)\}", css).group(1)
        self.assertIn("line-height: 1.2;", head)
        self.assertIn(".md-typeset .hp-filterbar:not([open]) { padding-bottom: 1rem; }", css)

    def test_clear_button_hovers_like_chips(self):
        # User pick (2026-11-06): same lift/glow/brightness hover the tag
        # chips have, tinted red like the button's own border, plus the
        # touch-device guard and an :active settle.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        rule = re.search(r"\.hp-filter-clear \{([^}]*)\}", css).group(1)
        self.assertIn("transition: transform .15s ease, box-shadow .15s ease, filter .15s ease;", rule)
        self.assertIn(
            ".hp-filter-clear:hover { transform: translateY(-2px); "
            "box-shadow: 0 4px 14px #ef44443d; filter: brightness(1.12); }", css)
        self.assertIn(
            ".hp-filter-clear:active { transform: translateY(0); "
            "box-shadow: 0 1px 4px #ef444433; }", css)
        self.assertIn(
            "@media (hover: none) { .hp-filter-clear:hover { transform: none; box-shadow: none; } }", css)

    def test_filter_chips_have_vertical_breathing_room(self):
        # User pick (2026-11-06): toolbar chips were touching vertically;
        # inside the filter bar only, they get real vertical padding and a
        # row gap so wrapped lines never collide. Entry-line chips untouched.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(
            ".hp-filter-chips a.hp-tag { padding: .2rem .5rem; margin: .18rem .1rem; }", css)
        # Must load after the base a.hp-tag rule to win the cascade.
        self.assertLess(css.index("a.hp-tag {"), css.index(".hp-filter-chips a.hp-tag {"))

    def test_tags_get_their_own_labelled_line(self):
        # User pick (2026-11-04): PoC V3 "labelled tag row" — the chips leave
        # the entry text flow: span.hp-tags becomes a block line under the
        # entry, prefixed with a muted monospace "tags:" label. Only CSS
        # changes; the span.hp-tags > a.hp-tag markup stays untouched, so the
        # live filter and the Tags-hub deep links keep working as-is.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(".hp-tags { display: block; margin-top: .35rem; }", css)
        self.assertIn('.hp-tags::before { content: "tags:";', css)
        self.assertNotIn(".hp-tags { display: inline; }", css)

    def test_badges_get_their_own_line_like_tags(self):
        # User pick (2026-11-06): stars/last-commit leave the entry text flow
        # the same way: span.hp-badges is a block line (rendered before the
        # tags line), the pills inside keep their inline chip style.
        # User pick (2026-11-06): the line gets a muted monospace
        # "repo stats:" label, mirroring the tags label rule exactly down to
        # the styling — only the content string differs.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(".hp-badges { display: block; margin-top: .35rem; }", css)
        self.assertIn('.hp-badges::before { content: "repo stats:";', css)
        tags_rule = css[css.index(".hp-tags::before {"):
                        css.index("}", css.index(".hp-tags::before {")) + 1]
        mirror = (tags_rule.replace('"tags:"', '"repo stats:"')
                             .replace(".hp-tags::before", ".hp-badges::before"))
        self.assertIn(mirror, css)

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
        # No top tag cloud (removed by user feedback 2026-11-05); each section
        # still opens with its resource count.
        self.assertNotIn("hp-cloud", hub)
        self.assertRegex(hub,
                         r'(?s)<a id="t-osint"></a>\n## osint\n\n'
                         r'<p class="hp-tagcount">\d+ resources?</p>')
        # Real catalog data drives the index (breach comes from 9Ghz/HIBP).
        self.assertIn('<a id="t-breach"></a>', hub)
        self.assertIn("[9Ghz](01_Recon_and_OSINT/OSINT/index.md#e-9ghz)", hub)
        self.assertIn("[Have I Been Pwned]"
                      "(01_Recon_and_OSINT/OSINT/index.md#e-have-i-been-pwned)", hub)
        # Each line shows the resource description, not its category path.
        self.assertIn("— Check if an email address is in a data breach.", hub)
        self.assertNotIn("class=\"where\"", hub)
        self.assertNotIn("· Reconnaissance and OSINT / OSINT", hub)

    def test_tags_filter_js_shipped(self):
        # S2: the live filter script is generated next to the theme assets.
        js = (self.docs / "javascripts" / "tags-filter.js").read_text(encoding="utf-8")
        for needle in ("hp-tag", "hp-tags", "hp-filterbar", "filter="):
            self.assertIn(needle, js)


class CollapsibleSidebar(unittest.TestCase):
    # Desktop (>1220px) pins the left nav beside the content; the generator
    # must ship a header toggle that hides it and reclaims the width.
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_sidebar_toggle_script_ships_in_config(self):
        self.assertIn('"javascripts/sidebar-toggle.js"', self.yml)

    def test_sidebar_toggle_js_shipped_with_persisted_state(self):
        js = (self.docs / "javascripts" / "sidebar-toggle.js").read_text(encoding="utf-8")
        # Button class, collapsed-state class, persistence and mount point.
        for needle in ("hp-nav-toggle", "hp-nav-collapsed", "localStorage",
                       "md-header__inner", "aria-pressed"):
            self.assertIn(needle, js)

    def test_collapse_css_is_desktop_only(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # Hidden below the drawer breakpoint: the off-canvas drawer and its
        # hamburger are native there, a second toggle would be noise.
        # Zensical ships ".md-header__button:not([hidden]){display:inline-block}"
        # at specificity (0,2,0), so a bare ".hp-nav-toggle{display:none}"
        # loses the cascade and leaks the button onto mobile (user report
        # 2026-11-04). The hide rule must out-specify it.
        self.assertIn(
            ".md-header .md-header__button.hp-nav-toggle { display: none; }", css)
        # At >=1220px the button appears (same specificity, later in file)
        # and the collapsed class hides the pinned sidebar; flex
        # .md-content then reclaims its 12.1rem.
        self.assertIn(
            "@media screen and (min-width: 1220px) { .md-header "
            ".md-header__button.hp-nav-toggle { display: inline-flex; } "
            "html.hp-nav-collapsed .md-sidebar--primary { display: none; } }",
            css)
        # The collapse rule must live inside the desktop media query: a
        # bare rule would also kill the drawer below 1220px.
        self.assertLess(css.index("@media screen and (min-width: 1220px)"),
                        css.index("html.hp-nav-collapsed .md-sidebar--primary"))

    def test_toggle_icons_are_distinct_per_state(self):
        # User (2026-11-04): no square; the glyph must read differently in
        # each state. Chevrons: << collapses the panel, >> expands it.
        js = (self.docs / "javascripts" / "sidebar-toggle.js").read_text(encoding="utf-8")
        self.assertIn("m11 17-5-5 5-5", js)   # chevrons-left  (visible)
        self.assertIn("m18 17-5-5 5-5", js)
        self.assertIn("m6 17 5-5-5-5", js)    # chevrons-right (collapsed)
        self.assertIn("m13 17 5-5-5-5", js)
        # The boxed panel frame is gone for good.
        self.assertNotIn("<rect", js)


class NavSections(unittest.TestCase):
    # Category groups are collapse toggles, but their open/closed state is
    # NEVER persisted: every load starts all-collapsed except the active
    # branch, which the static build opens automatically.

    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_no_static_section_feature_so_groups_stay_collapsible(self):
        # navigation.sections renders groups as static headers:
        # ".md-nav__item--section > .md-nav { display: block }" +
        # "pointer-events: none" on the label. Only the default nested nav
        # gives real collapse toggles. Regression pin for the user report
        # (2026-11-04): "The 17 sections are not collapseble".
        self.assertNotIn('"navigation.sections"', self.yml)
        # The other nav features must survive the surgery.
        for feature in ('"navigation.top"', '"navigation.footer"'):
            self.assertIn(feature, self.yml)

    def test_section_state_is_never_persisted(self):
        # User (2026-11-04, verbatim): "make it so the collapsed and not
        # collapsed is not saved. It should allways start with all collapsed."
        # The whole persistence layer is gone: no script, no config entry,
        # no storage key anywhere in the shipped JS.
        self.assertNotIn("nav-sections.js", self.yml)
        self.assertFalse((self.docs / "javascripts" / "nav-sections.js").exists())
        js = (self.docs / "javascripts" / "sidebar-toggle.js").read_text(encoding="utf-8")
        self.assertNotIn("hackpot.nav.sections.open", js)
        self.assertNotIn("md-nav__item--nested", js)
        # The panel-hide preference (hackpot.nav.collapsed) is separate and
        # deliberately still persists.
        self.assertIn("hackpot.nav.collapsed", js)


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


class RecentUploads(unittest.TestCase):
    # S1/S2 (odd/tasks/recent-uploads-view.md): a generated page compiling
    # "almost the last 50" uploaded resources — tool, description, uploader —
    # newest first, compiled from git history at site-generation time.

    DIFF = "\n".join([
        "@@C@@\tsha1\tRenovator\t1+renovator@users.noreply.github.com\t2026-11-05T10:00:00+01:00",
        "diff --git a/01_Recon_and_OSINT/OSINT/README.md b/01_Recon_and_OSINT/OSINT/README.md",
        "--- a/01_Recon_and_OSINT/OSINT/README.md",
        "+++ b/01_Recon_and_OSINT/OSINT/README.md",
        "@@ -5,0 +6,1 @@",
        "+- [9Ghz](https://9ghz.com/) — Retouched wording. `type:tool` `osint`",
        "+- [Overview bullet](../01_Recon_and_OSINT/README.md) — nav, not an upload. `x`",
        "@@C@@\tsha2\tFirst\t42+first@users.noreply.github.com\t2026-11-01T09:00:00+01:00",
        "diff --git a/01_Recon_and_OSINT/OSINT/README.md b/01_Recon_and_OSINT/OSINT/README.md",
        "--- a/01_Recon_and_OSINT/OSINT/README.md",
        "+++ b/01_Recon_and_OSINT/OSINT/README.md",
        "@@ -5,0 +6,1 @@",
        "+- [9Ghz](https://9ghz.com/) — Check if you are in any data breach. `type:tool` `osint`",
        "+- [HIBP](https://haveibeenpwned.com/) — Check if an email is pwned. `type:tool` `breach`",
        "@@C@@\tsha3\tDocwriter\t3+docs@users.noreply.github.com\t2026-10-20T09:00:00+01:00",
        "diff --git a/CONTRIBUTING.md b/CONTRIBUTING.md",
        "--- a/CONTRIBUTING.md",
        "+++ b/CONTRIBUTING.md",
        "@@ -1,0 +2,1 @@",
        "+- [Example](https://example.com) — outside the categories. `x`",
        "",
    ])

    def _add(self, name, date):
        return {"name": name, "url": "https://x.test/" + name,
                "desc": "does things.", "tags": [("tool", True)],
                "path": "01_Recon_and_OSINT/OSINT/README.md",
                "date": date, "iso": date + "T12:00:00+01:00", "login": "someone"}

    def test_parse_recent_diff_oldest_addition_wins_and_noise_is_dropped(self):
        adds = build_site.parse_recent_diff(self.DIFF)
        self.assertEqual({a["name"] for a in adds}, {"9Ghz", "HIBP"})
        nine = next(a for a in adds if a["name"] == "9Ghz")
        # The 2026-11-05 edit re-added the line but must not bump the upload:
        # date, wording and uploader all come from the FIRST addition.
        self.assertEqual(nine["date"], "2026-11-01")
        self.assertEqual(nine["desc"], "Check if you are in any data breach.")
        self.assertEqual(nine["login"], "first")
        self.assertEqual(nine["tags"], [("tool", True), ("osint", False)])

    def test_github_login_prefers_the_noreply_login(self):
        self.assertEqual(build_site.github_login(
            "46595866+J0nan@users.noreply.github.com", "Jonan"), "J0nan")
        self.assertEqual(build_site.github_login("mail@example.com", "Jonan"), "mail")
        self.assertEqual(build_site.github_login("", "Jonan"), "Jonan")

    def test_select_recent_keeps_only_live_entries_and_uses_page_anchor(self):
        adds = [self._add("Live", "2026-11-05"), self._add("Gone", "2026-11-04")]
        locs = {("01_Recon_and_OSINT/OSINT/index.md", "live"): "e-live"}
        rows = build_site.select_recent(adds, locs)
        self.assertEqual([r["name"] for r in rows], ["Live"])
        self.assertEqual(rows[0]["anchor"], "e-live")

    def test_select_recent_never_splits_a_same_day_batch_at_the_cap(self):
        adds = ([self._add(f"new{i:02d}", "2026-11-05") for i in range(48)]
                + [self._add(f"day{i:02d}", "2026-11-04") for i in range(4)]
                + [self._add(f"old{i:02d}", "2026-11-03") for i in range(3)])
        locs = {(build_site.site_doc(a["path"]), a["name"].casefold()):
                "e-" + a["name"].casefold() for a in adds}
        rows = build_site.select_recent(adds, locs, limit=build_site.RECENT_LIMIT)
        self.assertEqual(len(rows), 52)          # whole 2026-11-04 batch survives
        self.assertEqual(rows[-1]["date"], "2026-11-04")
        self.assertNotIn("2026-11-03", {r["date"] for r in rows})

    def test_select_recent_hard_stops_at_cap_plus_tie_bonus(self):
        # A single boundary day bigger than the cap must not blow the page up:
        # RECENT_LIMIT + at most RECENT_TIE_BONUS tie rows.
        adds = ([self._add(f"t{i:03d}", "2026-11-05") for i in range(60)]
                + [self._add(f"e{i:03d}", "2026-11-04") for i in range(5)])
        locs = {(build_site.site_doc(a["path"]), a["name"].casefold()):
                "e-" + a["name"].casefold() for a in adds}
        rows = build_site.select_recent(adds, locs, limit=build_site.RECENT_LIMIT)
        self.assertEqual(len(rows),
                         build_site.RECENT_LIMIT + build_site.RECENT_TIE_BONUS)

    def test_render_recent_row_shows_tool_description_and_uploader(self):
        # Chosen design (user pick 2026-11-06, POC V2): entry line, then the
        # uploader and date on their own credit line — avatar + @login +
        # human age + exact DD-MM-YYYY. No tag chips, so tags-filter.js
        # can never activate on this page (S4).
        rows = [
            {"name": "9Ghz", "doc": "01_Recon_and_OSINT/OSINT/index.md",
             "anchor": "e-9ghz", "desc": "Check if you are in any data breach.",
             "tags": [("tool", True), ("osint", False)], "login": "J0nan",
             "date": "2026-11-05", "iso": "2026-11-05T10:00:00+01:00"},
            {"name": "OldTool", "doc": "01_Recon_and_OSINT/OSINT/index.md",
             "anchor": "e-oldtool", "desc": "Was here before.", "tags": [],
             "login": "Vallejos115", "date": "2026-10-30",
             "iso": "2026-10-30T10:00:00+01:00"},
        ]
        ref = date(2026, 11, 10)
        page = build_site.render_recent(rows, ref=ref)
        self.assertTrue(page.startswith("# Recent uploads"))
        self.assertIn("- [9Ghz](01_Recon_and_OSINT/OSINT/index.md#e-9ghz) — "
                      "Check if you are in any data breach.", page)
        # own-line credit, human age, site date convention
        line = next(l for l in page.split("\n") if l.startswith("- [9Ghz]"))
        self.assertIn('<span class="hp-credit">', line)
        self.assertIn('src="https://github.com/J0nan.png?size=48"', line)
        self.assertIn("[@J0nan](https://github.com/J0nan)", line)
        self.assertIn("5 days ago (05-11-2026)", line)
        self.assertLess(page.index("[9Ghz]"), page.index("[OldTool]"),
                        "newest first")
        # S4: no chips anywhere on the page (data-tag anchors are what
        # tags-filter.js hunts for; hp-tag-sub is the intro paragraph).
        self.assertNotIn("hp-tags", page)
        self.assertNotIn('data-tag="', page)

    def test_upload_age_human_boundaries(self):
        ref = date(2026, 11, 10)
        cases = {"2026-11-10": "today", "2026-11-09": "yesterday",
                 "2026-10-28": "13 days ago", "2026-10-27": "2 weeks ago",
                 "2026-09-12": "8 weeks ago", "2026-09-11": "2 months ago",
                 "2025-09-16": "14 months ago"}
        for iso, want in cases.items():
            self.assertEqual(build_site.upload_age(iso, ref), want, iso)

    def test_render_recent_without_history_degrades_to_notice(self):
        page = build_site.render_recent([])
        self.assertTrue(page.startswith("# Recent uploads"))
        self.assertIn("history", page.lower())

    def test_credit_avatar_and_link_only_for_grammar_logins(self):
        # Risk finding R1 stays gated after the V2 redesign: avatar and
        # profile link may only be built from GitHub-grammar logins;
        # anything else degrades to harmless stripped text, no img, no a.
        good = {"name": "T", "doc": "d/index.md", "anchor": "e-t",
                "desc": "", "tags": [], "date": "2026-11-05",
                "iso": "2026-11-05T10:00:00+01:00"}
        ref = date(2026, 11, 12)
        page = build_site.render_recent([dict(good, login="a-b")], ref=ref)
        self.assertIn("https://github.com/a-b.png?size=48", page)
        self.assertIn("[@a-b](https://github.com/a-b)", page)
        evil = build_site.render_recent(
            [dict(good, login="ev[il](javascript:alert(1))x")], ref=ref)
        self.assertNotIn("javascript:", evil)
        self.assertNotIn("<img", evil)
        self.assertNotIn("](https", evil.split("</p>", 1)[1])
        self.assertIn("@eviljavascriptalert1x", evil)
        forty = build_site.render_recent([dict(good, login="a" * 40)], ref=ref)
        self.assertNotIn("<img", forty)
        self.assertIn("@" + "a" * 39, forty)
        blank = build_site.render_recent([dict(good, login="")], ref=ref)
        self.assertIn("@unknown", blank)
        self.assertNotIn("<img", blank)

    def test_shallow_checkout_yields_no_additions_not_misattribution(self):
        # Verifier advisory 1 (2026-11-05): in a depth-1 clone `git log -p`
        # diffs the boundary commit against the EMPTY tree, so every README
        # line parses as added by that one commit — wrong uploader and date
        # for every row, silently. The builder must refuse instead (the page
        # then degrades to the notice).
        git = shutil.which("git")
        if not git:
            self.skipTest("git not available")
        root = pathlib.Path(tempfile.mkdtemp(prefix="hackpot_shallow_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        origin, clone = root / "origin", root / "clone"
        env = {"GIT_AUTHOR_NAME": "First",
               "GIT_AUTHOR_EMAIL": "1+first@users.noreply.github.com",
               "GIT_COMMITTER_NAME": "First",
               "GIT_COMMITTER_EMAIL": "1+first@users.noreply.github.com"}

        def run(args, cwd, extra_env=None):
            e = dict(os.environ, **env)
            e.update(extra_env or {})
            r = subprocess.run([git, *args], cwd=str(cwd), capture_output=True,
                               text=True, env=e)
            self.assertEqual(r.returncode, 0, r.stderr)
        (origin / "01_Cat" / "Leaf").mkdir(parents=True)
        (origin / "01_Cat" / "Leaf" / "README.md").write_text(
            "# Leaf\n- [9Ghz](https://9ghz.com/) — First wording. `type:tool`\n",
            encoding="utf-8")
        run(["init", "-q"], origin)
        run(["add", "."], origin)
        run(["commit", "-q", "-m", "seed"], origin)
        (origin / "01_Cat" / "Leaf" / "README.md").write_text(
            "# Leaf\n- [9Ghz](https://9ghz.com/) — Reworded. `type:tool`\n",
            encoding="utf-8")
        run(["commit", "-q", "-am", "reword"], origin,
            {"GIT_AUTHOR_NAME": "Renovator",
             "GIT_COMMITTER_NAME": "Renovator"})
        # --depth is ignored in local-PATH clones; file:// forces a real
        # shallow fetch (git's own warning).
        url = origin.as_uri()
        run(["clone", "-q", "--depth", "1", url, str(clone)], root)
        self.assertEqual(build_site.recent_additions(cwd=clone), [])


class RecentUploadsGenerated(unittest.TestCase):
    # End-to-end over the real repo: the page is generated by build(), the
    # nav places it before Tags, and its deep links resolve.
    # Floor, not a pinned count: the POC measured 100% history coverage of
    # the live catalog (Log L3), so a build over this repo that finds far
    # fewer rows means the pipeline broke, not that the catalog shrank.
    MIN_LIVE_UPLOADS = 20

    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_recent_page_generated_before_tags_in_nav(self):
        self.assertIn('"Recent uploads": "recent.md"', self.yml)
        self.assertLess(self.yml.index('"Recent uploads": "recent.md"'),
                        self.yml.index('"Tags": "tags.md"'))
        page = (self.docs / "recent.md").read_text(encoding="utf-8")
        self.assertTrue(page.startswith("# Recent uploads"))

    def test_recent_rows_deep_link_existing_entry_anchors_and_uploaders(self):
        page = (self.docs / "recent.md").read_text(encoding="utf-8")
        links = re.findall(r"^- \[[^\]]+\]\(([^)]+)\)", page, re.M)
        if not links:
            self.skipTest("no git history available for this build")
        self.assertGreaterEqual(len(links), self.MIN_LIVE_UPLOADS)
        for target in links:
            path, frag = target.split("#", 1)
            text = (self.docs / path).read_text(encoding="utf-8")
            self.assertIn(f'<a id="{frag}"></a>', text, f"{target} dangling")
        # Chosen credit line (POC V2): avatar, profile link, human age and
        # the exact date in the site's DD-MM-YYYY convention.
        self.assertIn('<span class="hp-credit">', page)
        self.assertRegex(page, r"src=\"https://github\.com/[^\"]+\.png\?size=48\"")
        self.assertRegex(page, r"\[@[^\]]+\]\(https://github\.com/")
        self.assertRegex(page, r"\(\d{2}-\d{2}-\d{4}\)")
        # S4: the view carries no chips, so the filter toolbar never mounts.
        self.assertNotIn("hp-tags", page)
        self.assertLessEqual(len(links),
                             build_site.RECENT_LIMIT + build_site.RECENT_TIE_BONUS)

    def test_recent_credit_css_ships(self):
        # The own-line credit (S5) needs its classes in the shipped theme.
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(".hp-credit { display: block;", css)
        self.assertIn(".hp-avatar {", css)
        self.assertIn('[data-md-color-scheme="default"] .hp-credit', css)
        # Verifier regression (2026-11-05): chronological order is the whole
        # point of the view; pin it on the real generated page. Dates are
        # rendered DD-MM-YYYY inside the credit line.
        page = (self.docs / "recent.md").read_text(encoding="utf-8")
        stamp = re.findall(r"\((\d{2})-(\d{2})-(\d{4})\)", page)
        iso = [f"{y}-{m}-{d}" for d, m, y in stamp]
        if not iso:
            self.skipTest("no git history available for this build")
        self.assertEqual(iso, sorted(iso, reverse=True))


if __name__ == "__main__":
    unittest.main()
