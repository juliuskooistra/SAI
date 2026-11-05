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

Typed in, not stored in a file or in your shell history. (`printf` + `read -rs`
works in both zsh, the Mac's shell, and bash; `read -p` is bash only.)

```bash
printf "MLMP key (Enter to skip): "; read -rs MLMP_KEY; echo
printf "Password for the 'staff' account (10+ chars): "; read -rs STAFF_PW; echo
printf "Password for the 'customer' account (10+ chars): "; read -rs CUSTOMER_PW; echo
printf "Password for the 'admin' account (10+ chars): "; read -rs ADMIN_PW; echo
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
AZURE_RESOURCE_GROUP=$RG bash deploy/azure/release.sh bikeshop $NAME.azurecr.io/bikeshop:2
```

**Never deploy with a plain `az containerapp update`.** Azure would start the
new version while the old one still runs, and for a minute or two both copy
the database to the same place in Blob Storage. That can break the copy for
good: the next start fails in `litestream restore` and the app stays down
(it happened to staging on 2026-11-04, SPEC §10.2). `release.sh` (through
`update.sh`) stops the old version first, waits until it is gone, then
starts the new one and waits for `/health`. The app is away for about a
minute. The same goes for any setting that restarts the app: use
`deploy/azure/update.sh <app> --set-env-vars …`. `az containerapp secret set`
doesn't restart it and needs no script.

If a copy is broken anyway, don't repair it in place: restore its last good
point to a file on your laptop (`litestream restore -txid <id> -o …`), check
it with `sqlite3 … "PRAGMA integrity_check"`, replicate it once to a **new**
path, and set the app's `LITESTREAM_PATH` to that path with `update.sh`.
Staging was rebuilt like this and now uses `bikeshop-staging-v2`.

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
AZURE_RESOURCE_GROUP=$RG bash deploy/azure/update.sh bikeshop \
  --set-env-vars SHOP_STAFF_EMAIL=<the shop's address>
```

The email only leaves the log once the app has a Mailgun key (EU region,
a sending key for the `mail.kooistra.ch` domain):

```bash
printf "Mailgun key: "; read -rs MG_KEY; echo
az containerapp secret set --name bikeshop --resource-group $RG --secrets "mailgun-key=$MG_KEY"
AZURE_RESOURCE_GROUP=$RG bash deploy/azure/update.sh bikeshop --set-env-vars MAILGUN_API_KEY=secretref:mailgun-key
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

## The Workshop (staff's AI maintenance agent)

The Workshop (SPEC §14) needs **no new package, secret, setting or service**. It
uses the MLMP key the assistant already has, and the pipeline deploys it like any
other change. Its tables appear by themselves at the first start, and no existing
row changes. Only its demo data is added by hand, once per app.

You need the Azure CLI, signed in, with access to the `bikeshop-rg` resource group.

**1. Merge the pull request.** The pipeline tests it, builds the image and deploys
it to staging. Don't approve production yet.

**2. Check staging.** Wake it up and open a shell inside it:

```bash
RG=bikeshop-rg
curl -s https://$(az containerapp show --name bikeshop-staging --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)/health      # wake it up
az containerapp exec --name bikeshop-staging --resource-group $RG --command sh
```

Inside the container, check that this app's MLMP key may use the Workshop's model.
`/health` can't tell you: it only tests the assistant's model.

```bash
python -c "from api import config; from api.services.inference_service import InferenceService as I; print(config.WORKSHOP_MODEL, config.WORKSHOP_MODEL in [m.id for m in I().get_client().models.list()])"
```

It must print `glm-5.3-flash True`. If it prints `False`, see the table below.

**3. Add the data**, still inside the container. Both scripts are safe to run again:
each one prints `skipped` if its data is already there. They take seconds.

```bash
python -m scripts.seed_history       # a year of past usage; the Workshop needs its customers
python -m scripts.seed_workshop      # prints "20 bikes, 10 suppliers, … rentals"
```

Wait about 10 seconds before you `exit`, so Litestream has copied the new rows.
The dates count from the day you run it, and **it runs only once per database**,
so run it close to the lecture: a planted "pick-up tomorrow" doesn't stay tomorrow.

**4. Try it on staging.** Sign in as `staff`, open *Workshop*, open a case and press
**Analyse with the agent**. The brief usually takes 3 to 10 minutes, the model thinks
long before it writes. Keep the page open.

**5. Approve production** in the Actions tab, then repeat steps 2 and 3 with
`--name bikeshop`.

Good to know:

- **The seed adds invented data to the app**: 20 rental bikes, invented bookings
  on them, 10 fictional suppliers and scans. Customers see the new bikes. Its
  customers have `.test` addresses, so no email goes to anyone.
- **Keep the page open during an analysis.** The page asks for news every 2 seconds,
  which keeps the app awake. If everyone leaves, the app scales to zero and the
  round stops. Nothing is lost: on the next visit the case says "The agent stopped"
  and **Retry** carries on.
- **Tokens**: one analysis used about 64,000 tokens of the MLMP key in our test. The
  agent stays under 20 requests and 100,000 tokens a minute, leaving room for the
  website's assistant, and it waits by itself when MLMP is busy.
- **A rollback is safe**: re-run the production job of an earlier successful run. The
  old version ignores the Workshop's tables, and they're there again when you
  redeploy. Run a rollback while no analysis is running. Bikes that staff put
  in maintenance stay in maintenance.

To use another model, for example if the deployment's key isn't allowed
`glm-5.3-flash` (this restarts the app, and the model must support tool calls):

```bash
AZURE_RESOURCE_GROUP=$RG bash deploy/azure/update.sh bikeshop --set-env-vars WORKSHOP_MODEL=<model>
```

| what you see | cause | fix |
|---|---|---|
| "BFH inference is not configured" when you press Analyse | the app has no MLMP key | `printf "MLMP key: "; read -rs MLMP_KEY; echo`, `az containerapp secret set --name <app> --resource-group $RG --secrets "mlmp-key=$MLMP_KEY"`, then `AZURE_RESOURCE_GROUP=$RG bash deploy/azure/update.sh <app> --set-env-vars MLMP_API_KEY=secretref:mlmp-key` |
| the model check prints `False` | this key may not use the model | ask for access, or set `WORKSHOP_MODEL` as above |
| "The agent stopped" | the app restarted or scaled to zero during a round | press **Retry** |
| "The AI service took too long to answer" | one model call passed the 240-second limit, most likely the one that writes the brief | press **Retry**: the agent carries on from where it was |
| "The AI service refused the key" | the MLMP key is wrong or expired (they last 180 days) | set a new key as in the first row |
| "Waiting for AI capacity" | MLMP's limits, shared with the assistant | nothing: the agent carries on by itself |
| `Run python -m scripts.seed and scripts.seed_history first.` | the app has no history yet | run `scripts.seed_history`, then the seed again |
| the *Workshop* list is empty | the seed hasn't run on this app | step 3 |

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
| `AuthorizationFailed` in `az acr login` or a deploy (`release.sh`, `update.sh`) | the role assignment is missing | the `az role assignment create` lines above |

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
