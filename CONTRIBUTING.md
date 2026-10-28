# Contributing to Hackpot

Hackpot is a curated, category-first index of penetration-testing resources. This guide keeps the list consistent as it grows.

## Where things live

- `NN_Domain_Name/README.md` — top-level category, numbered and `Title_Cased_With_Underscores`.
- `NN_Domain_Name/Sub_Category/README.md` — leaf category that holds the actual entries.
- Each leaf README has a `## Resources` section. That is where entries go.

## Entry format

One bullet per resource:

```markdown
- [Name](https://canonical-url) — What it does and why it matters. `type:tool` `linux`
```

Rules:

- Entries are alphabetical by display name within `## Resources`.
- One line per entry. Say why it is useful, not only what it is.
- Link the canonical source (project page, repository, docs) — not mirrors or forks.
- Tags are optional but encouraged:
  - Type: ``type:tool``, `type:course`, `type:docs`, `type:wordlist`, `type:lab`, `type:article`, `type:video`
  - Platform or tech as needed: `linux`, `windows`, `aws`, `gdb`, ...
  - On the website the trailing tokens render as clickable tag bubbles at the
    page bottom (and in a whole-site tag index at Tags), not inside the entry
    text — keep writing them exactly as above.
- Do **not** add star counts, popularity badges, or "last updated" notes manually: CI appends them automatically on the site for entries linking a GitHub repository.

## License

By contributing, you agree that your contributions are licensed under the GPL-3.0-only license (see [LICENSE](LICENSE)).
