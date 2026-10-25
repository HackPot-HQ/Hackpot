"""Shared helpers for Hackpot CI scripts (link metadata extraction)."""

import re
import urllib.parse

# Markdown links pointing at github.com: [Name](https://github.com/owner/repo...)
GITHUB_LINK_RE = re.compile(
    r"\[[^\]]*\]\((https://github\.com/[^\s)]+)(?:\s+\"[^\"]*\")?\)"
)
GITHUB_URL_RE = re.compile(r"https://github\.com/[^\s)\]>\"']+")

# Second path segment values that are not repository names.
NON_REPO_SEGMENTS = {
    "issues", "pulls", "pull", "releases", "discussions", "actions",
    "security", "wiki", "about", "install", "settings", "topics",
    "collection", "features", "login", "signup", "sponsors", "orgs",
    "codespaces", "gists", "marketplace", "pricing", "enterprise",
}


def github_slug(url: str):
    """Return 'owner/repo' for a github.com URL, or None if it is not a repo URL."""
    try:
        parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] in NON_REPO_SEGMENTS:
        return None
    repo = parts[1]
    if repo.lower() in NON_REPO_SEGMENTS:
        return None
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo:
        return None
    return f"{parts[0]}/{repo}"


def extract_github_slugs(text: str):
    """Return the set of owner/repo slugs referenced by markdown links in text."""
    slugs = set()
    for match in GITHUB_LINK_RE.finditer(text):
        slug = github_slug(match.group(1))
        if slug:
            slugs.add(slug)
    return slugs
