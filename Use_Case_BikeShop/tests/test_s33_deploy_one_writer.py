"""
S33: one writer per database copy (SPEC §10.2, §10.4).

The deploy scripts run against a fake `az` and a fake `curl` that write down
every call, so we can check the order without Azure: the old revision is
stopped and gone before the new one is made, and then /health is checked.
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

# The fake az: answers what the scripts ask, from environment variables
FAKE_AZ = r"""#!/usr/bin/env bash
echo "az $*" >> "$CALLS"
case "$*" in
  "extension add"*)              exit 0 ;;
  "containerapp revision list"*) printf '%s\n' $FAKE_ACTIVE ;;
  "containerapp revision deactivate"*) exit "${FAKE_DEACTIVATE_EXIT:-0}" ;;
  "containerapp revision show"*replicas*)
      # Replicas left: counts down by one per question, from FAKE_REPLICAS
      n=$(cat "$STATE/replicas" 2>/dev/null || echo "${FAKE_REPLICAS:-0}")
      echo "$n"; [ "$n" -gt 0 ] && echo $((n - 1)) > "$STATE/replicas"
      [ -n "${FAKE_STUCK:-}" ] && echo "${FAKE_REPLICAS}" > "$STATE/replicas"
      exit 0 ;;
  "containerapp revision show"*runningState*) echo "Running" ;;
  "containerapp update"*)        echo "$*" > "$STATE/updated" ;;
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
            "FAKE_ACTIVE": "app--old", "FAKE_HEALTH": HEALTHY,
            **env,
        }
        result = subprocess.run(["bash", str(script), *args], env=environment,
                                capture_output=True, text=True, timeout=60)
        log = calls.read_text().splitlines() if calls.exists() else []
        return result, log

    return run


def index(log, pattern):
    """Position of the first call matching `pattern`."""
    return next(i for i, line in enumerate(log) if re.search(pattern, line))


def test_old_revision_is_gone_before_the_new_one_is_made(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_REPLICAS="2")
    assert result.returncode == 0, result.stderr
    stop = index(log, r"revision deactivate .*--revision app--old")
    last_check = max(i for i, line in enumerate(log) if "revision show" in line)
    update = index(log, r"containerapp update ")
    health = index(log, r"^curl .*https://app\.example\.net/health")
    assert stop < last_check < update < health
    # It asked until the count reached 0: 2, 1, 0
    assert sum("revision show" in line and "replicas" in line for line in log) == 3


def test_every_active_revision_is_stopped(fake):
    # e.g. two crash-looping revisions, as on staging on 2026-11-05
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_ACTIVE="app--a app--b")
    assert result.returncode == 0, result.stderr
    assert index(log, "deactivate .*app--a") < index(log, "containerapp update ")
    assert index(log, "deactivate .*app--b") < index(log, "containerapp update ")


def test_no_change_when_the_old_revision_cannot_be_stopped(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_DEACTIVATE_EXIT="1")
    assert result.returncode != 0
    assert "was not changed" in result.stderr
    assert not any("containerapp update " in line for line in log)


def test_no_change_when_the_old_revision_keeps_running(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE,
                       FAKE_REPLICAS="1", FAKE_STUCK="1", STOP_WAIT_SECONDS="1")
    assert result.returncode != 0
    assert "still runs" in result.stderr and "revision activate" in result.stderr
    assert not any("containerapp update " in line for line in log)


def test_a_rerun_with_the_same_image_still_makes_a_revision(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE)
    assert result.returncode == 0, result.stderr
    update = log[index(log, "containerapp update ")]
    assert re.search(r"--revision-suffix d\d{14}\b", update)
    assert f"--image {IMAGE}" in update


def test_health_is_waited_for_with_a_limit(fake):
    result, log = fake(UPDATE, "app", "--image", IMAGE, FAKE_HEALTH="", HEALTH_WAIT_SECONDS="1")
    assert result.returncode != 0
    assert "app did not become healthy" in result.stderr
    assert all("--max-time 20" in line for line in log if line.startswith("curl "))


def test_health_needs_the_database(fake):
    result, _ = fake(UPDATE, "app", "--image", IMAGE,
                     FAKE_HEALTH='{"status":"degraded","database":"error"}', HEALTH_WAIT_SECONDS="1")
    assert result.returncode != 0


def test_update_needs_something_to_change(fake):
    result, log = fake(UPDATE, "app")
    assert result.returncode == 2
    assert not any("deactivate" in line for line in log)


def test_release_deploys_through_update_and_checks_the_image(fake):
    result, log = fake(RELEASE, "app", IMAGE)
    assert result.returncode == 0, result.stderr
    assert index(log, "deactivate") < index(log, "containerapp update ") < index(log, r"show .*image")
    assert f"app runs {IMAGE}" in result.stdout


def test_runbook_has_no_plain_update_of_a_running_app():
    """DEPLOY-azure.md: every command that makes a revision goes through the scripts."""
    runbook = (APP_DIR / "DEPLOY-azure.md").read_text()
    plain = [line for line in runbook.splitlines()
             if re.search(r"(^\s*|`)az containerapp update --name\b", line)]   # a command line, or one in `…`
    assert plain == [], f"use deploy/azure/update.sh instead: {plain}"
