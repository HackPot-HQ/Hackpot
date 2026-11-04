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


if __name__ == "__main__":
    for f in (test_reaper_does_not_call_nonexistent_list_endpoint,
              test_reaper_state_case_covers_observed_classic_statuses,
              test_deploy_needs_build_and_reaper):
        f()
        print(f.__name__, "OK")
