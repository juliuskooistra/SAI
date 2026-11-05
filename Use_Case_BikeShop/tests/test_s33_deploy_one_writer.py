"""
S33: one writer per database copy (SPEC §10.2, §10.4).

The deploy scripts run against a fake `az` and a fake `curl` that write down
every call, so we can check the order without Azure: the app is stopped and
nothing runs any more before the new revision is made, the app is started
only after that, and is never left stopped when something fails.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
UPDATE = APP_DIR / "deploy" / "azure" / "update.sh"
RELEASE = APP_DIR / "deploy" / "azure" / "release.sh"
IMAGE = "reg.azurecr.io/bikeshop:abc1234"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# The fake az: answers what the scripts ask, steered by FAKE_* variables.
# FAKE_REPLICAS: replicas still running after the stop, one fewer per question
# (FAKE_STUCK keeps them running).
FAKE_AZ = r"""#!/usr/bin/env bash
echo "az $*" >> "$CALLS"
case "$*" in
  "extension add"*) exit 0 ;;
  "rest --method post --url "*/stop*)  [ -n "${FAKE_STOP_FAILS:-}" ] && exit 1
                                      touch "$STATE/stopped"; exit 0 ;;
  "rest --method post --url "*/start*) [ -n "${FAKE_START_FAILS:-}" ] && exit 1
                                      rm -f "$STATE/stopped"; exit 0 ;;
  "containerapp show"*"--query id"*) echo "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerapps/app" ;;
  "containerapp show"*runningStatus*)
      if [ -f "$STATE/stopped" ]; then echo Stopped; else echo Running; fi ;;
  "containerapp revision list"*)
      n=$(cat "$STATE/replicas" 2>/dev/null || echo "${FAKE_REPLICAS:-0}")
      echo "$n"
      if [ -z "${FAKE_STUCK:-}" ] && [ "$n" -gt 0 ]; then echo $((n - 1)) > "$STATE/replicas"; fi ;;
  "containerapp update"*)
      [ -n "${FAKE_UPDATE_FAILS:-}" ] && exit 1
      echo "$*" > "$STATE/updated" ;;
  "containerapp show"*ingress.fqdn*) echo "app.example.net" ;;
  "containerapp show"*image*)
      grep -o -- '--image [^ ]*' "$STATE/updated" 2>/dev/null | cut -d' ' -f2 ;;
  *) echo "fake az: unexpected call: $*" >&2; exit 9 ;;
esac
"""

FAKE_CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$CALLS"
if [ -n "${FAKE_HEALTH:-}" ]; then echo "$FAKE_HEALTH"; else exit 22; fi
"""

HEALTHY = '{"status":"ok","database":"ok"}'


@pytest.fixture
def fake(tmp_path):
    """A bin folder with fake az and curl first on PATH, and the log of their calls."""
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for name, body in (("az", FAKE_AZ), ("curl", FAKE_CURL)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    calls = tmp_path / "calls.log"

    def run(script, *args, **env):
        environment = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls), "STATE": str(state),
            "AZURE_RESOURCE_GROUP": "rg", "POLL_SECONDS": "0",
            "FAKE_HEALTH": HEALTHY,
            **env,
        }
        result = subprocess.run(["bash", str(script), *args], env=environment,
                                capture_output=True, text=True, timeout=60)
        log = calls.read_text().splitlines() if calls.exists() else []
        return result, log

    return run


def index(log, pattern, last=False):
    """Position of the first (or last) call matching `pattern`."""
    found = [i for i, line in enumerate(log) if re.search(pattern, line)]
    assert found, f"no call matching {pattern!r}"
    return found[-1] if last else found[0]


STOP, START = r"rest --method post .*/containerapps/app/stop\?", r"rest --method post .*/containerapps/app/start\?"
UPDATE_CALL = r"containerapp update "


def test_nothing_runs_when_the_new_revision_is_made(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_REPLICAS="2")
    assert result.returncode == 0, result.stderr
    stop = index(log, STOP)
    last_check = index(log, r"revision list .*--all", last=True)
    update = index(log, UPDATE_CALL)
    start = index(log, START)
    health = index(log, r"^curl .*https://app\.example\.net/health")
    assert stop < last_check < update < start < health
    # It asked until no replica was left: 2, 1, 0
    assert sum("revision list" in line for line in log) == 3
    assert sum(re.search(START, line) is not None for line in log) == 1


def test_no_change_when_the_app_cannot_be_stopped(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_STOP_FAILS="1")
    assert result.returncode != 0
    assert "was not changed" in result.stderr
    assert not any(re.search(UPDATE_CALL, line) for line in log)
    assert not any(re.search(START, line) for line in log)   # it never stopped


def test_started_again_when_it_keeps_running(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE,
                       FAKE_REPLICAS="1", FAKE_STUCK="1", STOP_WAIT_SECONDS="1")
    assert result.returncode != 0
    assert "still runs" in result.stderr and "Starting app again" in result.stderr
    assert not any(re.search(UPDATE_CALL, line) for line in log)
    assert index(log, STOP) < index(log, START)


def test_started_again_when_the_update_fails(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_UPDATE_FAILS="1")
    assert result.returncode != 0
    assert "keeps its old revision" in result.stderr
    assert index(log, UPDATE_CALL) < index(log, START)


def test_a_failed_start_says_what_to_do(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_START_FAILS="1")
    assert result.returncode != 0
    assert "start it in the portal" in result.stderr
    assert sum(re.search(START, line) is not None for line in log) == 1   # not tried twice
    assert not any(line.startswith("curl ") for line in log)


def test_a_rerun_with_the_same_image_still_makes_a_revision(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE)
    assert result.returncode == 0, result.stderr
    update = log[index(log, UPDATE_CALL)]
    assert re.search(r"--revision-suffix d\d{14}\b", update)
    assert f"--image {IMAGE}" in update


def test_health_is_waited_for_with_a_limit(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_HEALTH="", HEALTH_WAIT_SECONDS="1")
    assert result.returncode != 0
    assert "app did not become healthy" in result.stderr
    assert all("--max-time 20" in line for line in log if line.startswith("curl "))
    assert sum(re.search(START, line) is not None for line in log) == 1   # started once, not again


def test_health_needs_the_database(fake):
    result, _ = fake(UPDATE, "app", "--image", IMAGE,
                     FAKE_HEALTH='{"status":"degraded","database":"error"}', HEALTH_WAIT_SECONDS="1")
    assert result.returncode != 0


def test_update_needs_something_to_change(fake):
    result, log = fake(UPDATE, "app")
    assert result.returncode == 2
    assert not any(re.search(STOP, line) for line in log)


def test_release_deploys_through_update_and_checks_the_image(fake):
    result, log = fake(RELEASE, "app", IMAGE)
    assert result.returncode == 0, result.stderr
    assert index(log, STOP) < index(log, UPDATE_CALL) < index(log, START) < index(log, r"show .*image")
    assert f"app runs {IMAGE}" in result.stdout


def test_runbook_has_no_plain_update_of_a_running_app():
    """DEPLOY-azure.md: every command that makes a revision goes through the scripts."""
    runbook = (APP_DIR / "DEPLOY-azure.md").read_text()
    plain = [line for line in runbook.splitlines()
             if re.search(r"(^\s*|`)az containerapp update --name\b", line)]   # a command line, or one in `…`
    assert plain == [], f"use deploy/azure/update.sh instead: {plain}"
