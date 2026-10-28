"""Regression tests for scripts/build_site.py."""

import pathlib
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
        build_site.build(out, repo_url="https://github.com/J0nan/Hackpot")
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

    def test_search_and_tags_plugins(self):
        # Built-in search configured via the search entry; native tags plugin.
        self.assertRegex(self.yml, r"(?m)^\s*-\s*\"?search\"?\s*$")
        self.assertRegex(self.yml, r"(?m)^\s*-\s*\"?tags\"?\s*$")

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


class PageTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()

    def test_controlled_tag_extraction_and_yaml_escaping(self):
        # Hermetic unit for the tag pipeline: namespace stripping (including
        # a space after the prefix), dedupe, whitespace, empty values, and
        # exact YAML-safe emission of quote/backslash-bearing tags.
        src = (
            "# T\n\n"
            "- [A](https://x.test/a) — a. `type:tool` ` free ` `dup` `dup`\n"
            "- [B](https://x.test/b) — b. `type:` `type: spaced` `wei\"rd` `back\\slash`\n"
            "Not a list item: `ignored`\n"
        )
        self.assertEqual(build_site.page_tags(src),
                         ["tool", "free", "dup", "spaced", 'wei"rd', "back\\slash"])
        # Exact emission (not just "escape chars appear somewhere"): the
        # document must be a tags list of properly escaped scalars.
        self.assertEqual(
            build_site.front_matter(['wei"rd', "back\\slash"]),
            '---\ntags:\n- "wei\\"rd"\n- "back\\\\slash"\n---\n')
        self.assertEqual(build_site.front_matter([]), "")

    def test_leaf_pages_get_tags_front_matter_from_source_tokens(self):
        # Tokens in source READMEs become page-level tags. Since generated
        # bodies have their inline tokens stripped, discovery goes via front
        # matter.
        tagged = None
        for p in self.docs.rglob("index.md"):
            if p.parent == self.docs:
                continue
            text = p.read_text(encoding="utf-8")
            if text.startswith("---\ntags:\n"):
                tagged = p
                break
        self.assertIsNotNone(tagged, "no page with tags front matter found")
        front = tagged.read_text(encoding="utf-8").split("---\n", 2)[1]
        self.assertRegex(front, r"(?m)- \"(tool|docs)\"")

    def test_home_and_contributing_have_no_front_matter(self):
        for name in ("index.md", "contributing.md"):
            p = self.docs / name
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
        src = "# T\n\n- [HackBar](https://github.com/d3vilbug/HackBar) — x. `type:tool` `free`\n"
        out = build_site.transform(src, {}, "https://github.com/J0nan/Hackpot")
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
        # "Soft Lift" hover style on tag chips.
        self.assertIn("a.md-tag:hover { transform: translateY(-2px)", css)
        self.assertIn("a.md-tag { transition:", css)
        self.assertIn("a.md-tag:active", css)
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

    def test_tag_bubbles_no_sticky_hover_on_touch(self):
        css = (self.docs / "stylesheets" / "theme.css").read_text(encoding="utf-8")
        # The tag bubbles lift -2px on hover; on touch that lift sticks after
        # a tap, so the guard must cover them the same way it covers pills.
        self.assertIn(
            "@media (hover: none) { .hp-badge:hover { transform: none; "
            "box-shadow: none; } a.md-tag:hover { transform: none; box-shadow: none; } }",
            css)

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

    def test_tags_hub_page_emitted_and_in_nav(self):
        hub = (self.docs / "tags.md").read_text(encoding="utf-8")
        self.assertIn("<!-- material/tags -->", hub)
        self.assertIn('"Tags": "tags.md"', self.yml)


class TagDedupe(unittest.TestCase):
    # Entry pages show tags ONLY as footer bubbles.
    @classmethod
    def setUpClass(cls):
        cls.docs = cached_build()

    def test_generated_tagged_pages_have_no_residue_tag_tokens(self):
        checked = 0
        for p in self.docs.rglob("index.md"):
            text = p.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue  # home/contributing keep their prose untouched
            body = text.split("---\n", 2)[2]
            self.assertEqual(build_site.page_tags(body), [],
                             f"tag tokens still inline in {p}")
            checked += 1
        self.assertGreaterEqual(checked, 1, "expected at least one tagged page")
        # entry bullets themselves survive (names stay searchable)
        leaf = self.docs / "08_Web_Application" / "Vulnerability_Specific" / "index.md"
        self.assertIn("[HackBar]", leaf.read_text(encoding="utf-8"))

    def test_transform_unit_strip_only_removes_tokens(self):
        src = "- [X](https://x.test) — does things. `type:tool` `free`\n"
        kept = build_site.transform(src, {}, None)
        self.assertIn("`type:tool`", kept)  # old behavior intact by default
        stripped = build_site.transform(src, {}, None, drop_tag_tokens=True)
        self.assertEqual(stripped, "- [X](https://x.test) — does things.\n")

    def test_strip_keeps_inline_code_in_description(self):
        # Only the TRAILING tag run is removed; inline code in the prose stays.
        src = "- [X](https://x.test) — uses `nmap` scripts. `type:tool` `free`\n"
        stripped = build_site.transform(src, {}, None, drop_tag_tokens=True)
        self.assertEqual(stripped, "- [X](https://x.test) — uses `nmap` scripts.\n")

    def test_fenced_example_bullets_are_untouched(self):
        # Doc examples inside ``` fences keep their literal tag tokens.
        src = (
            "- [X](https://x.test) — real entry. `free`\n\n"
            "```markdown\n"
            "- [Name](https://example.com) — what it does. `type:tool` `free`\n"
            "```\n"
        )
        out = build_site.transform(src, {}, None, drop_tag_tokens=True)
        self.assertIn(
            "- [Name](https://example.com) — what it does. `type:tool` `free`", out)
        self.assertIn("- [X](https://x.test) — real entry.\n", out)


if __name__ == "__main__":
    unittest.main()
