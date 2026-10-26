"""Regression tests for scripts/build_site.py (S1-S5, odd/tasks/zensical-migration.md)."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_site  # noqa: E402


def fresh_build():
    tmp = tempfile.mkdtemp(prefix="hackpot_build_site_")
    out = pathlib.Path(tmp) / "docs"
    build_site.build(out, repo_url="https://github.com/J0nan/Hackpot")
    return out


class EmittedConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = fresh_build()
        # Zensical requires site_dir within the project root (= config dir),
        # so build_site.py emits the config next to docs/, not inside it.
        cls.yml = (cls.docs.parent / "mkdocs.yml").read_text(encoding="utf-8")

    def test_uses_zensical_variant_not_material_name(self):
        # S1: Zensical replaces Material; variant classic keeps the current look.
        self.assertIn('variant: "classic"', self.yml)
        self.assertNotIn('name: "material"', self.yml)

    def test_site_dir_in_config(self):
        # S5: Zensical has no --site-dir, so site_dir must live in config,
        # within the project root.
        self.assertIn('site_dir: "site"', self.yml)
        self.assertIn('docs_dir: "docs"', self.yml)

    def test_search_and_tags_plugins(self):
        # S1/S2: built-in search configured via the search entry; native tags plugin.
        self.assertRegex(self.yml, r"(?m)^\s*-\s*\"?search\"?\s*$")
        self.assertRegex(self.yml, r"(?m)^\s*-\s*\"?tags\"?\s*$")

    def test_search_highlight_feature(self):
        self.assertIn('"search.highlight"', self.yml)

    def test_palette_emits_auto_light_dark_toggle(self):
        # S3: dark and light themes with automatic system-preference mode.
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
        cls.docs = fresh_build()

    def test_leaf_pages_get_tags_front_matter_from_inline_tokens(self):
        # S2: inline backtick tokens become page-level tags for the native
        # tags plugin (searchable + filterable in Zensical search).
        leaf = None
        for p in self.docs.rglob("index.md"):
            if p.parent == self.docs:
                continue
            text = p.read_text(encoding="utf-8")
            if "`type:tool`" in text or "`type:docs`" in text:
                leaf = p
                break
        self.assertIsNotNone(leaf, "no leaf page with tagged entries found")
        text = leaf.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "expected YAML front matter")
        front = text.split("---", 2)[1]
        self.assertIn("tags:", front)
        # type: namespace stripped to real values, free tags kept raw.
        self.assertRegex(front, r"(?m)- \"(tool|docs)\"")

    def test_home_and_contributing_have_no_front_matter(self):
        for name in ("index.md", "contributing.md"):
            p = self.docs / name
            if p.exists():
                self.assertFalse(p.read_text(encoding="utf-8").startswith("---\n"))


class Badges(unittest.TestCase):
    def test_not_found_uses_literal_emoji(self):
        # S1: no Material emoji shortcodes (:warning:) — Zensical must render
        # the warning without emoji-extension config.
        meta = {"repos": {"owner/repo": {"not_found": True}}}
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertIn("\u26a0\ufe0f", suffix)
        self.assertNotIn(":warning:", suffix)

    def test_stars_suffix_unchanged(self):
        meta = {"repos": {"owner/repo": {"stars": 12000, "last_update": "2026-10-01"}}}
        suffix = build_site.badge_suffix("[X](https://github.com/owner/repo) — x", meta)
        self.assertEqual(suffix, " · **★ 12.0k** · updated 2026-10-01")

    def test_entry_lines_survive_transform(self):
        # Differential pin: content pages must keep their entry bullets.
        src = "# T\n\n- [HackBar](https://github.com/d3vilbug/HackBar) — x. `type:tool` `free`\n"
        out = build_site.transform(src, {}, "https://github.com/J0nan/Hackpot")
        self.assertIn("- [HackBar](https://github.com/d3vilbug/HackBar)", out)
        self.assertIn("`type:tool`", out)


if __name__ == "__main__":
    unittest.main()
