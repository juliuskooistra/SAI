#!/usr/bin/env bash
# Deploy one image to one container app and wait until it's healthy
# (SPEC §10.4). Used by the GitHub workflow for staging and production; also
# works from a laptop after `az login`.
#
#   AZURE_RESOURCE_GROUP=bikeshop-rg bash deploy/azure/release.sh bikeshop-staging <registry>.azurecr.io/bikeshop:<tag>
set -euo pipefail

APP="$1"
IMAGE="$2"
RG="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"

az extension add --name containerapp --upgrade --only-show-errors >/dev/null

echo "Deploying $IMAGE to $APP"
az containerapp update --name "$APP" --resource-group "$RG" --image "$IMAGE" --only-show-errors -o none

# The app's own address, not the custom domain, so a certificate problem
# can't hide whether the deployment worked
FQDN=$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)
RUNNING=$(az containerapp show --name "$APP" --resource-group "$RG" --query "properties.template.containers[0].image" -o tsv)
[ "$RUNNING" = "$IMAGE" ] || { echo "Expected $IMAGE, the app has $RUNNING" >&2; exit 1; }

# Wait up to 5 minutes: the app may first have to wake up and restore its database
for attempt in $(seq 1 30); do
  if HEALTH=$(curl -fsS --max-time 60 "https://$FQDN/health") && grep -q '"database":"ok"' <<<"$HEALTH"; then
    echo "Healthy: $HEALTH"
    exit 0
  fi
  echo "Not healthy yet (attempt $attempt), waiting 10 s"
  sleep 10
done
echo "$APP did not become healthy within 5 minutes" >&2
exit 1
