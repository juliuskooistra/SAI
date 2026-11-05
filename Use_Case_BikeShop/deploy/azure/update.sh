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
#   1. stops the whole app and waits until nothing runs; Litestream copies its
#      last changes when it gets the stop signal,
#   2. makes the new revision while the app is stopped (it is made, not run),
#   3. starts the app, which runs only the new revision,
#   4. waits until /health says the database is ok.
# Stopping only the old revision is not enough: during an update Azure starts
# the last ready revision again (seen 2026-11-05). The price is about a minute
# of downtime. If step 1 fails, nothing changes; if anything fails after it,
# the app is started again, so it is never left stopped.
set -euo pipefail

APP="${1:?Usage: update.sh <app> <az containerapp update arguments>}"
shift
if [ "$#" -eq 0 ]; then
  echo "Say what to change, e.g. --image <registry>.azurecr.io/bikeshop:<hash>" >&2
  exit 2
fi
RG="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"

STOP_WAIT_SECONDS="${STOP_WAIT_SECONDS:-120}"     # for the app to stop
HEALTH_WAIT_SECONDS="${HEALTH_WAIT_SECONDS:-300}" # for the new revision to be healthy (start + restore)
POLL_SECONDS="${POLL_SECONDS:-5}"                 # between checks (the tests set 0)
API_VERSION="2026-07-01"                          # Microsoft.App, for stop and start (no az command)

az extension add --name containerapp --upgrade --only-show-errors >/dev/null

APP_ID=$(az containerapp show --name "$APP" --resource-group "$RG" --query id -o tsv)

# stop / start the whole app: every revision
app_action() {
  az rest --method post --url "https://management.azure.com${APP_ID}/$1?api-version=${API_VERSION}" -o none
}

# After a successful stop, the app is started again however the script ends
started=yes
start_again() {
  if [ "$started" = no ]; then
    echo "Starting $APP again" >&2
    app_action start || echo "Could not start $APP: start it in the portal (Overview, Start)" >&2
    started=yes
  fi
}
trap start_again EXIT

# ---------------------------------------------------------------- 1. stop the app
echo "Stopping $APP"
if ! app_action stop; then
  echo "Could not stop $APP, so it was not changed." >&2
  exit 1
fi
started=no

stopped() {
  local status running
  status=$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.runningStatus -o tsv)
  running=$(az containerapp revision list --name "$APP" --resource-group "$RG" --all \
              --query "length([?properties.replicas > \`0\`])" -o tsv)
  [ "$status" = "Stopped" ] && [ "$running" = "0" ]
}

start=$SECONDS
until stopped; do
  if [ $((SECONDS - start)) -ge "$STOP_WAIT_SECONDS" ]; then
    echo "$APP still runs after ${STOP_WAIT_SECONDS} s, so it was not changed." >&2
    exit 1   # start_again brings the old revision back
  fi
  sleep "$POLL_SECONDS"
done
echo "$APP has stopped"

# ---------------------------------------------------------------- 2. make the new revision
# A unique suffix, so a new revision is made even when nothing else changed
# (e.g. a re-run with the same image)
SUFFIX="d$(date -u +%Y%m%d%H%M%S)"
echo "Updating $APP (revision $APP--$SUFFIX): $*"
if ! az containerapp update --name "$APP" --resource-group "$RG" --revision-suffix "$SUFFIX" \
       "$@" --only-show-errors -o none; then
  echo "The update failed; $APP keeps its old revision." >&2
  exit 1   # start_again brings the old revision back
fi

# ---------------------------------------------------------------- 3. start it
echo "Starting $APP"
if ! app_action start; then
  echo "Could not start $APP: start it in the portal (Overview, Start)" >&2
  started=yes   # don't try again in start_again
  exit 1
fi
started=yes

# ---------------------------------------------------------------- 4. wait until it's healthy
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
