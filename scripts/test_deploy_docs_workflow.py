"""Contract tests for the Pages-deployment reaper in deploy-docs.yml.

Facts: github/rest-api-description (api.github.com.json) defines only
POST /pages/deployments, GET /pages/deployments/{id}, POST .../cancel;
statuses-with-state live in the classic Deployments API, where this repo's
github-pages environment has shown: waiting, queued, in_progress, success,
failure (documented set adds error, active, inactive, pending)."""
import pathlib
import re

import yaml

WF = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/deploy-docs.yml"
WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows"


def _script():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))[
        "jobs"]["clear-stale-deployment"]["steps"][0]["run"]


def test_reaper_does_not_call_nonexistent_list_endpoint():
    assert not re.search(r"gh api[^\n]*pages/deployments\?per_page", _script()), \
        "GET /repos/{o}/{r}/pages/deployments is not a real route (404, generic doc URL)"


def test_reaper_state_case_covers_observed_classic_statuses():
    for state in ("waiting", "queued", "in_progress", "success", "failure"):
        assert re.search(rf"\b{state}\b", _script()), f"state '{state}' unhandled"


def test_deploy_needs_build_and_reaper():
    needs = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["deploy"]["needs"]
    assert {"build", "clear-stale-deployment"} <= set(needs)


def test_workflows_checkout_full_history_for_recent_uploads():
    """docs/recent.md is compiled from git history at build time; the
    actions/checkout default depth of 1 would ship an empty view."""
    for name in ("deploy-docs.yml", "site-check.yml"):
        doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        steps = doc["jobs"]["build"]["steps"]
        checkouts = [s for s in steps
                     if str(s.get("uses", "")).startswith("actions/checkout@")]
        assert checkouts, f"{name}: no actions/checkout step found"
        for step in checkouts:
            assert str(step.get("with", {}).get("fetch-depth")) == "0", \
                f"{name}: checkout must set fetch-depth: 0"


if __name__ == "__main__":
    for f in (test_reaper_does_not_call_nonexistent_list_endpoint,
              test_reaper_state_case_covers_observed_classic_statuses,
              test_deploy_needs_build_and_reaper,
              test_workflows_checkout_full_history_for_recent_uploads):
        f()
        print(f.__name__, "OK")
