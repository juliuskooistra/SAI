#!/usr/bin/env bash
# Deploy one image to one container app and wait until it's healthy
# (SPEC §10.4). Used by the GitHub workflow for staging and production; also
# works from a laptop after `az login`, and for a rollback to an earlier image.
#
#   AZURE_RESOURCE_GROUP=bikeshop-rg bash deploy/azure/release.sh bikeshop-staging <registry>.azurecr.io/bikeshop:<tag>
#
# The work is done by update.sh: it stops the running revision before it
# starts the new one, so two copies never write the database (SPEC §10.2).
set -euo pipefail

APP="${1:?Usage: release.sh <app> <image>}"
IMAGE="${2:?Usage: release.sh <app> <image>}"
RG="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"

echo "Deploying $IMAGE to $APP"
bash "$(dirname "$0")/update.sh" "$APP" --image "$IMAGE"

RUNNING=$(az containerapp show --name "$APP" --resource-group "$RG" \
            --query "properties.template.containers[0].image" -o tsv)
if [ "$RUNNING" != "$IMAGE" ]; then
  echo "Expected $IMAGE, the app has $RUNNING" >&2
  exit 1
fi
echo "$APP runs $IMAGE"
