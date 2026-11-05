#!/usr/bin/env bash
# Change a container app in a way that makes a new revision, and never let
# two revisions run at the same time (SPEC §10.2, "One writer per database copy").
#
#   AZURE_RESOURCE_GROUP=bikeshop-rg bash deploy/azure/update.sh <app> <az containerapp update arguments>
#
#   e.g.  update.sh bikeshop-staging --image <registry>.azurecr.io/bikeshop:<hash>
#         update.sh bikeshop --set-env-vars WORKSHOP_MODEL=<model>
#
# Why: by default Azure starts the new revision before it stops the old one.
# For a minute or two both run, and both copy the database to the same
# Litestream path. That can break the copy for good (it did on 2026-11-04:
# every later start failed in `litestream restore`). So this script
#   1. stops (deactivates) the running revision and waits until it is gone;
#      Litestream copies its last changes when it gets the stop signal,
#   2. only then makes the new revision,
#   3. waits until /health says the database is ok.
# The price is about a minute of downtime. If step 1 fails, nothing changes.
set -euo pipefail

APP="${1:?Usage: update.sh <app> <az containerapp update arguments>}"
shift
if [ "$#" -eq 0 ]; then
  echo "Say what to change, e.g. --image <registry>.azurecr.io/bikeshop:<hash>" >&2
  exit 2
fi
RG="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"

STOP_WAIT_SECONDS="${STOP_WAIT_SECONDS:-120}"     # for the old revision to stop
HEALTH_WAIT_SECONDS="${HEALTH_WAIT_SECONDS:-300}" # for the new one to be healthy (wake-up + restore)
POLL_SECONDS="${POLL_SECONDS:-5}"                 # between checks (the tests set 0)

az extension add --name containerapp --upgrade --only-show-errors >/dev/null

# ---------------------------------------------------------------- 1. stop the old revision
ACTIVE=$(az containerapp revision list --name "$APP" --resource-group "$RG" \
           --query "[?properties.active].name" -o tsv)

for rev in $ACTIVE; do
  echo "Stopping $rev"
  if ! az containerapp revision deactivate --name "$APP" --resource-group "$RG" \
         --revision "$rev" --only-show-errors -o none; then
    echo "Could not stop $rev, so $APP was not changed." >&2
    exit 1
  fi
done

# A revision has stopped when it has no replica left
revision_field() {
  az containerapp revision show --name "$APP" --resource-group "$RG" --revision "$1" \
    --query "properties.$2" -o tsv 2>/dev/null || true
}
stopped() {
  local replicas state
  replicas=$(revision_field "$1" replicas)
  [ "$replicas" = "0" ] && return 0
  # No count at all: trust only a state that says it is gone
  if [ -z "$replicas" ] || [ "$replicas" = "None" ]; then
    state=$(revision_field "$1" runningState)
    [ "$state" = "Stopped" ] || [ "$state" = "Deprovisioned" ]
    return
  fi
  return 1
}

start=$SECONDS
for rev in $ACTIVE; do
  until stopped "$rev"; do
    if [ $((SECONDS - start)) -ge "$STOP_WAIT_SECONDS" ]; then
      echo "$rev still runs after ${STOP_WAIT_SECONDS} s, so $APP was not changed." >&2
      echo "It is deactivated: to bring it back, az containerapp revision activate --name $APP --resource-group $RG --revision $rev" >&2
      exit 1
    fi
    sleep "$POLL_SECONDS"
  done
  echo "$rev has stopped"
done

# ---------------------------------------------------------------- 2. make the new revision
# A unique suffix, so a new revision is made even when nothing else changed
# (e.g. a re-run with the same image): otherwise the app would stay stopped.
SUFFIX="d$(date -u +%Y%m%d%H%M%S)"
echo "Updating $APP (revision $APP--$SUFFIX): $*"
az containerapp update --name "$APP" --resource-group "$RG" --revision-suffix "$SUFFIX" \
  "$@" --only-show-errors -o none

# ---------------------------------------------------------------- 3. wait until it's healthy
# The app's own address, not the custom domain, so a certificate problem
# can't hide whether the deployment worked
FQDN=$(az containerapp show --name "$APP" --resource-group "$RG" \
         --query properties.configuration.ingress.fqdn -o tsv)

start=$SECONDS
attempt=0
while :; do
  attempt=$((attempt + 1))
  if HEALTH=$(curl -fsS --max-time 20 "https://$FQDN/health") && grep -q '"database":"ok"' <<<"$HEALTH"; then
    echo "Healthy: $HEALTH"
    exit 0
  fi
  if [ $((SECONDS - start)) -ge "$HEALTH_WAIT_SECONDS" ]; then
    break
  fi
  echo "Not healthy yet (attempt $attempt), waiting"
  sleep "$POLL_SECONDS"
done
echo "$APP did not become healthy within ${HEALTH_WAIT_SECONDS} s." >&2
echo "Its start-up log: az containerapp logs show --name $APP --resource-group $RG --type console --tail 50" >&2
exit 1
