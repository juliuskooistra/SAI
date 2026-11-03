# Deploying BikeShop to Azure Container Apps

Your own copy of BikeShop on the internet, paid per use, from an **Azure for
Students** subscription ($100 credit, no credit card). SPEC §10.2 explains the
design; this is the step-by-step.

```text
browser ─HTTPS─► bikeshop (FastAPI: API + website, and the worker, under Litestream)
                     └─ copies the database every second ─► Azure Blob Storage
```

One container app serves the API and the website. The container keeps no files. When nobody uses the app for a few minutes, it
**scales to zero** and costs nothing; the next visitor wakes it up (about
10–30 seconds). Litestream restores the database from Blob Storage on every
start, so your data survives.

## What it costs

| Part | Cost |
|---|---|
| Container Apps | per second while running; a demo that's mostly idle stays inside the free monthly allowance |
| Container Registry (Basic) | about $5 a month, also when idle: **delete everything when you're done** (last step) |
| Blob Storage, logs | cents |

Azure for Students never charges a card: when the credit is used up, the
subscription stops.

## 0. What you need

- An Azure for Students subscription: <https://azure.microsoft.com/free/students>,
  sign in with your BFH account.
- The Azure CLI: `brew install azure-cli` (Mac), or see
  <https://learn.microsoft.com/cli/azure/install-azure-cli>. If `az` says
  `AZ_PYTHON not set` (Homebrew installed outside `/opt/homebrew`), add
  `export AZ_PYTHON="$(brew --prefix)/opt/python@3.14/bin/python3.14"` to your `~/.zshrc`.
- Docker Desktop, running: the image is built on your laptop (step 4).
- This repository, and an MLMP key from <https://access.mlmp.ti.bfh.ch>
  (optional: without it, `/health` shows `"inference": "not_configured"`).

```bash
git clone https://github.com/juliuskooistra/SAI.git
cd SAI/Use_Case_BikeShop
```

## 1. Sign in and prepare the subscription (once)

```bash
az login
az extension add --name containerapp --upgrade
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.Storage; do
  az provider register --namespace $ns
done
```

## 2. Names and region

```bash
LOCATION=switzerlandnorth          # Azure for Students allows: switzerlandnorth, francecentral, italynorth, austriaeast, belgiumcentral
RG=bikeshop-rg
NAME=bikeshop$RANDOM               # registry and storage names must be unique in all of Azure
echo "Your name: $NAME"            # write it down; the steps below use it

az group create --name $RG --location $LOCATION
```

## 3. Storage for the database copy

```bash
az storage account create --name $NAME --resource-group $RG --location $LOCATION \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false
STORAGE_KEY=$(az storage account keys list --account-name $NAME --resource-group $RG --query "[0].value" -o tsv)
az storage container create --name litestream --account-name $NAME --account-key "$STORAGE_KEY"
```

## 4. Build the image and push it to your registry

Azure for Students doesn't allow building in Azure (`az acr build` answers
"ACR Tasks requests … are not permitted"), so Docker builds it on your
laptop. `--platform linux/amd64` builds for Azure's processors, also on an
Apple Silicon Mac.

```bash
az acr create --name $NAME --resource-group $RG --sku Basic --admin-enabled true
az acr login --name $NAME
docker buildx build --platform linux/amd64 -t $NAME.azurecr.io/bikeshop:1 --push .
ACR_PW=$(az acr credential show --name $NAME --query "passwords[0].value" -o tsv)
```

## 5. Secrets

Typed in, not stored in a file or in your shell history:

```bash
read -s -p "MLMP key (Enter to skip): " MLMP_KEY; echo
read -s -p "Password for the 'staff' account (10+ chars): " STAFF_PW; echo
read -s -p "Password for the 'customer' account (10+ chars): " CUSTOMER_PW; echo
read -s -p "Password for the 'admin' account (10+ chars): " ADMIN_PW; echo
API_KEY_SECRET=$(openssl rand -base64 36)
```

## 6. Start the app

```bash
az containerapp env create --name bikeshop-env --resource-group $RG --location $LOCATION

az containerapp create --name bikeshop --resource-group $RG --environment bikeshop-env \
  --image $NAME.azurecr.io/bikeshop:1 \
  --registry-server $NAME.azurecr.io --registry-username $NAME --registry-password "$ACR_PW" \
  --ingress external --target-port 8000 \
  --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
  --secrets "mlmp-key=${MLMP_KEY:-none}" "api-key-secret=$API_KEY_SECRET" \
            "storage-key=$STORAGE_KEY" "staff-pw=$STAFF_PW" "customer-pw=$CUSTOMER_PW" "admin-pw=$ADMIN_PW" \
  --env-vars APP_MODE=all SEED_ON_START=1 UVICORN_WORKERS=2 \
             LITESTREAM_AZURE_ACCOUNT_NAME=$NAME LITESTREAM_AZURE_CONTAINER=litestream \
             LITESTREAM_AZURE_ACCOUNT_KEY=secretref:storage-key \
             MLMP_API_KEY=secretref:mlmp-key API_KEY_SECRET=secretref:api-key-secret \
             SEED_STAFF_PASSWORD=secretref:staff-pw SEED_CUSTOMER_PASSWORD=secretref:customer-pw \
             ADMIN_PASSWORD=secretref:admin-pw

URL=https://$(az containerapp show --name bikeshop --resource-group $RG --query properties.configuration.ingress.fqdn -o tsv)
curl -s $URL/health
echo "Open $URL   (API docs: $URL/docs)"
```

Pass the registry's username and password as above: the CLI creates an
"Express" environment, which can't pull with a managed identity, and
`--registry-server` alone fails with `ExpressEnvironmentFeatureNotSupported`.

**`--max-replicas 1` matters**: two copies would each restore the database
and then overwrite each other's copy in Blob Storage.

Sign in as `admin`, `staff` or `customer` with the passwords from step 5.

## 7. Scale to zero, in practice

After about 5 minutes without visitors the app stops (you can't make that
longer on this environment type). Open pages keep working in the browser;
the next click shows "Waking up the shop…" for 10–30 seconds while the
container starts and restores the database. Before a demo, open the app a
minute early.

## 8. Check that the data survives

1. Book a bike as `customer`.
2. Deploy a new image (the next section): Azure starts a fresh container and
   throws the old one away, disk and all. Check that the replica is new:
   `az containerapp replica list --name bikeshop --resource-group $RG --query "[].properties.createdTime" -o tsv`
3. Open *My rentals* again: the booking is still there, restored from Blob
   Storage.

Or simply leave the app alone for 10 minutes (it scales to zero) and open it
again.

## Updating after a code change

```bash
az acr login --name $NAME
docker buildx build --platform linux/amd64 -t $NAME.azurecr.io/bikeshop:2 --push .
az containerapp update --name bikeshop --resource-group $RG --image $NAME.azurecr.io/bikeshop:2
```

For a few seconds the old and the new version run side by side; a booking
made in exactly those seconds can be lost. Fine for a demo, not for a real
shop: that's when you move to a managed database (see [MAP.md](MAP.md)).

## Automatic deployment with GitHub Actions (optional)

`.github/workflows/bikeshop.yml` tests every push; on `main` it builds the
image, deploys it to staging, and after your approval the same image to
production (SPEC §10.4). It logs in to Azure with GitHub's OIDC token and a
**managed identity**: no password ends up in GitHub. (BFH accounts can't
register Azure apps, but they can create managed identities.)

Once, in Azure: the identity, what it may do, and which GitHub runs may use it.
These commands grant permissions, so read them before you run them:

```bash
REPO=<your-github-user>/<your-repo>          # e.g. juliuskooistra/SAI
az identity create --name bikeshop-github --resource-group $RG --location $LOCATION
PID=$(az identity show --name bikeshop-github --resource-group $RG --query principalId -o tsv)

# Which runs may log in: pushes to main, and the two environments
for pair in "github-main:repo:$REPO:ref:refs/heads/main" \
            "github-staging:repo:$REPO:environment:staging" \
            "github-production:repo:$REPO:environment:production"; do
  az identity federated-credential create --name ${pair%%:*} --identity-name bikeshop-github \
    --resource-group $RG --issuer https://token.actions.githubusercontent.com \
    --subject "${pair#*:}" --audiences api://AzureADTokenExchange
done

# What it may do: push images, change the two apps. Nothing else.
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal \
  --role AcrPush --scope $(az acr show --name $NAME --query id -o tsv)
for app in bikeshop bikeshop-staging; do
  az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal \
    --role Contributor --scope $(az containerapp show --name $app --resource-group $RG --query id -o tsv)
done
```

Once, in GitHub (with the `gh` CLI, or under *Settings → Secrets and
variables → Actions → Variables* and *Settings → Environments*):

```bash
gh variable set AZURE_CLIENT_ID --repo $REPO --body "$(az identity show --name bikeshop-github --resource-group $RG --query clientId -o tsv)"
gh variable set AZURE_TENANT_ID --repo $REPO --body "$(az account show --query tenantId -o tsv)"
gh variable set AZURE_SUBSCRIPTION_ID --repo $REPO --body "$(az account show --query id -o tsv)"
gh variable set AZURE_RESOURCE_GROUP --repo $REPO --body "$RG"
gh variable set ACR_NAME --repo $REPO --body "$NAME"
gh api -X PUT repos/$REPO/environments/staging
# production waits for your approval:
gh api -X PUT repos/$REPO/environments/production --input - <<JSON
{"reviewers": [{"type": "User", "id": $(gh api user --jq .id)}]}
JSON
```

From then on: merge to `main` → tests → image `bikeshop:<commit>` →
staging → you approve in the Actions tab → production. To roll back, re-run
the production job of an earlier successful run.

## Logs and status

```bash
az containerapp logs show --name bikeshop --resource-group $RG --follow
curl -s $URL/health      # database, inference, last expiry run, worker, queue
```

The worker (background jobs such as emails, and the reservation expiry) only
runs while the app is awake. When it wakes up, it first catches up: expired
reservations are released and queued emails go out; `/health` shows when it
last ran.

## 9. Delete everything when you're done

```bash
az group delete --name $RG --yes --no-wait
```

This removes the app, the registry, the storage and the database copy. It
stops all costs.
