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

Every later step uses `$RG` and `$NAME`. In a **new terminal** they are
empty, and `az` answers `argument --resource-group/-g: expected one
argument`. Set them again:

```bash
RG=bikeshop-rg
NAME=$(az acr list --resource-group $RG --query "[0].name" -o tsv)
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
az containerapp env create --name bikeshop-env --resource-group $RG --location $LOCATION \
  --environment-mode ConsumptionOnly

az containerapp create --name bikeshop --resource-group $RG --environment bikeshop-env \
  --image $NAME.azurecr.io/bikeshop:1 \
  --registry-server $NAME.azurecr.io --registry-username $NAME --registry-password "$ACR_PW" \
  --ingress external --target-port 8000 \
  --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
  --secrets "mlmp-key=${MLMP_KEY:-none}" "api-key-secret=$API_KEY_SECRET" \
            "storage-key=$STORAGE_KEY" "staff-pw=$STAFF_PW" "customer-pw=$CUSTOMER_PW" "admin-pw=$ADMIN_PW" \
  --env-vars APP_MODE=all SEED_ON_START=1 UVICORN_WORKERS=2 METRICS_ENABLED=0 \
             LITESTREAM_AZURE_ACCOUNT_NAME=$NAME LITESTREAM_AZURE_CONTAINER=litestream \
             LITESTREAM_AZURE_ACCOUNT_KEY=secretref:storage-key \
             MLMP_API_KEY=secretref:mlmp-key API_KEY_SECRET=secretref:api-key-secret \
             SEED_STAFF_PASSWORD=secretref:staff-pw SEED_CUSTOMER_PASSWORD=secretref:customer-pw \
             ADMIN_PASSWORD=secretref:admin-pw

URL=https://$(az containerapp show --name bikeshop --resource-group $RG --query properties.configuration.ingress.fqdn -o tsv)
curl -s $URL/health
echo "Open $URL   (API docs: $URL/docs)"
```

`--environment-mode ConsumptionOnly` makes a classic pay-per-use
environment. Without it the CLI may create an "Express" one, which can't
take a custom domain or pull images with a managed identity
(`ExpressEnvironmentFeatureNotSupported`), see SPEC §10.2. The registry's
username and password work with both.

`METRICS_ENABLED=0`: on Azure, `/metrics` would be public.

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

## A staging copy (needed for the GitHub pipeline)

A second app in the same environment: same image, **its own database**
(SPEC §10.2). Run it in the shell from steps 2–5 (it needs `$STORAGE_KEY`
and the passwords):

```bash
az containerapp create --name bikeshop-staging --resource-group $RG --environment bikeshop-env \
  --image $NAME.azurecr.io/bikeshop:1 \
  --registry-server $NAME.azurecr.io --registry-username $NAME --registry-password "$ACR_PW" \
  --ingress external --target-port 8000 \
  --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
  --secrets "mlmp-key=${MLMP_KEY:-none}" "api-key-secret=$(openssl rand -base64 36)" \
            "storage-key=$STORAGE_KEY" "staff-pw=$STAFF_PW" "customer-pw=$CUSTOMER_PW" "admin-pw=$ADMIN_PW" \
  --env-vars APP_MODE=all SEED_ON_START=1 UVICORN_WORKERS=2 METRICS_ENABLED=0 \
             LITESTREAM_PATH=bikeshop-staging \
             LITESTREAM_AZURE_ACCOUNT_NAME=$NAME LITESTREAM_AZURE_CONTAINER=litestream \
             LITESTREAM_AZURE_ACCOUNT_KEY=secretref:storage-key \
             MLMP_API_KEY=secretref:mlmp-key API_KEY_SECRET=secretref:api-key-secret \
             SEED_STAFF_PASSWORD=secretref:staff-pw SEED_CUSTOMER_PASSWORD=secretref:customer-pw \
             ADMIN_PASSWORD=secretref:admin-pw
```

**`LITESTREAM_PATH=bikeshop-staging` matters**: two apps on the same path
would overwrite each other's database. Staging gets no Mailgun key, so its
emails only go to the log.

Release by hand: update staging to the new image, check `/health` and a
booking, then update production to the **same** tag.

## Your own domain (optional)

For example `demo.sai1.airs.iadsf.ch` for `bikeshop`, `staging.sai1.airs.iadsf.ch`
for `bikeshop-staging`. In your DNS:

| record | value |
|---|---|
| `CNAME demo.sai1` | the app's address (`az containerapp show … --query properties.configuration.ingress.fqdn`) |
| `TXT asuid.demo.sai1` | `az containerapp env show --name bikeshop-env --resource-group $RG --query properties.customDomainConfiguration.customDomainVerificationId -o tsv` |
| `CAA sai1.airs.iadsf.ch` | `0 issue "digicert.com"`: without it the free certificate stays "Pending" when a parent domain's CAA records don't allow DigiCert (SPEC §10.2) |

Then let Azure issue the certificate:

```bash
az containerapp hostname add  --name bikeshop --resource-group $RG --hostname demo.sai1.airs.iadsf.ch
az containerapp hostname bind --name bikeshop --resource-group $RG --hostname demo.sai1.airs.iadsf.ch \
  --environment bikeshop-env --validation-method CNAME
```

## The AI assistant on the website

The *Assistant* page (SPEC §13.8) needs the MLMP key from step 5; without it
the page says "The assistant is not available right now." Its hand-off to
staff emails one address. Set it on an app that already runs (this restarts
it):

```bash
az containerapp update --name bikeshop --resource-group $RG \
  --set-env-vars SHOP_STAFF_EMAIL=<the shop's address>
```

Without `SHOP_STAFF_EMAIL` the assistant has no hand-off tool and tells
customers to contact the shop. On staging (no Mailgun key) the email only
goes to the log.

## A year of past usage (optional)

`scripts/seed_history.py` adds a year of invented customers, rentals, sales
and analytics, with planted patterns (SPEC §9.1). Run it by hand inside the
running app, **staging first**. Its dates count from the day you run it, so
run it close to the demo:

```bash
curl -s https://$(az containerapp show --name bikeshop-staging --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)/health      # wake it up
az containerapp exec --name bikeshop-staging --resource-group $RG --command sh
python -m scripts.seed_history       # inside the container; prints "… rentals, … analytics events"
exit
```

Wait about 10 seconds before you leave, so Litestream has copied the new rows.
Running it again prints `history exists, skipped`. Then the same for
`--name bikeshop`.

## Getting at the data

The database is a SQLite file inside the container: there's no port to
connect to. To develop against it (SPEC §8.2):

- **A local copy with the same data** (best for development): run
  `scripts.seed`, then `scripts.seed_history` on your laptop (README).
- **The deployed app's API**, with a staff API key: `/staff/analytics?days=365`,
  `/staff/rentals`, and the rest of `/docs`.
- **A read-only snapshot** of the real data: `litestream restore` from the
  storage account (needs the storage key). Never write it back.

Don't write to the deployed file from outside the app: Litestream expects
one writer.

## Automatic deployment with GitHub Actions (optional)

`.github/workflows/bikeshop.yml` tests every push; on `main` it builds the
image, deploys it to staging, and after your approval the same image to
production (SPEC §10.4). It logs in to Azure with GitHub's OIDC token and a
**managed identity**: no password ends up in GitHub. (BFH accounts can't
register Azure apps, but they can create managed identities.) It needs the
staging app from above.

**Don't use the portal's *Continuous deployment*** (or `az containerapp
github-action add`) for this. It commits a second workflow that deploys
straight to production on every push, without tests, staging or approval,
and it fails anyway, because the Dockerfile isn't in the repository root.
If it was switched on, delete `.github/workflows/*AutoDeployTrigger*.yml` and
the `BIKESHOP_*` secrets it created, and turn it off under the app's
*Continuous deployment* blade.

Once, in Azure: the identity, what it may do, and which GitHub runs may use it.
These commands grant permissions, so read them before you run them:

```bash
REPO=<your-github-user>/<your-repo>          # e.g. juliuskooistra/SAI
az identity create --name bikeshop-github --resource-group $RG --location $LOCATION
PID=$(az identity show --name bikeshop-github --resource-group $RG --query principalId -o tsv)

# Which runs may log in: pushes to main, and the two environments
# Write ${REPO} with braces: in zsh, "$REPO:r…" and "$REPO:e…" are modifiers
# that silently cut the text (subject "repo:nvironment:staging")
for pair in "github-main|repo:${REPO}:ref:refs/heads/main" \
            "github-staging|repo:${REPO}:environment:staging" \
            "github-production|repo:${REPO}:environment:production"; do
  az identity federated-credential create --name "${pair%%|*}" --identity-name bikeshop-github \
    --resource-group $RG --issuer https://token.actions.githubusercontent.com \
    --subject "${pair#*|}" --audiences api://AzureADTokenExchange
done
# Check: each subject must read repo:<user>/<repo>:ref:… or …:environment:…
az identity federated-credential list --identity-name bikeshop-github --resource-group $RG \
  --query "[].subject" -o tsv

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

**When the pipeline fails:**

| error in the run | cause | fix |
|---|---|---|
| `Unable to resolve action …@vN` | a pinned action version doesn't exist | pin an existing tag (`gh api repos/<owner>/<action>/releases/latest`) |
| `Not all values are present. Ensure 'client-id' and 'tenant-id' are supplied` | the repository **variables** are missing (secrets with other names don't count) | `gh variable list`; set them as above |
| `AADSTS700213: No matching federated identity record found for … subject 'repo:…'` | the federated credential's subject differs from the one in the error | compare with `az identity federated-credential list …`; fix with `az identity federated-credential update` |
| `AuthorizationFailed` in `az acr login` or `az containerapp update` | the role assignment is missing | the `az role assignment create` lines above |

Fix, then `gh run rerun <run id>` (the id is in the run's URL).

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
