# What BikeShop costs on Azure

An estimate per month for the set-up in [DEPLOY-azure.md](DEPLOY-azure.md):
Switzerland North, one production app and one staging app, scale to zero.
Prices are Azure's list prices in **USD** from the official
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices),
checked on 3 November 2026. Your bill in CHF depends on the exchange rate.

## The short answer

| Use | Per month |
|---|---|
| A class demo: awake about 50 hours a month in total | **about $6** |
| Busy: production awake 8 hours every weekday, staging now and then | **about $10–11** |
| Always on (never scales to zero) | **about $28** |

With Azure for Students ($100 a year), the demo set-up runs for the whole
year. **Most of the cost is the container registry, which is charged even when
nothing runs.** Delete the resource group when you're done (step 9 of the
runbook).

## Line by line

| What | Price (Switzerland North) | Our use | Per month |
|---|---|---|---|
| **Container Registry**, Basic | $0.1666 per day, 10 GB included | always there | **$5.07** |
| **Container Apps**, compute while awake | vCPU $0.000024/s, memory $0.000003/GiB·s | 0.5 vCPU + 1 GiB = **$0.054 per awake hour** per app | see below |
| ↳ free every month | 180,000 vCPU·s + 360,000 GiB·s | = the first **100 awake hours** (all apps together) | −100 h |
| ↳ requests | $0.40 per million, first 2 million free | a few thousand | $0 |
| ↳ environment (Consumption only) | no fixed fee | | $0 |
| ↳ managed certificates | free | 2 | $0 |
| **Blob Storage** (Litestream's database copy), Hot LRS | $0.0216 per GB, $0.054 per 10,000 writes | a few MB; writes only while the app is awake and data changes | < $0.25 |
| **Log Analytics** (logs) | first 5 GB free, then $3.289 per GB | a few MB | $0 |
| **Alerts**: 2 metric rules | first 10 free | 5xx, restarts | $0 |
| **Alerts**: 2 log rules, every 15 min | $0.50 each | exceptions, failed jobs | $1.00 |
| **Outgoing traffic** | first 100 GB free | a few hundred MB | $0 |

### How "awake hours" add up

An app is awake from the first visit until **one hour after the last
request** (the scale-down delay, SPEC §10.2). It's billed for that whole time,
then nothing until the next visit.

| Scenario | Awake hours (prod + staging) | Compute after the free 100 h | Total with registry, storage, alerts |
|---|---|---|---|
| Class demo: 10 sessions of 3 h, plus 20 h of testing | 50 h | $0 | **≈ $6.3** |
| Busy: 8 h × 20 weekdays + 20 h staging | 180 h | 80 h × $0.054 = $4.32 | **≈ $10.6** |
| Always on, both apps (min. 1 instance) | 1,460 h, mostly at the lower idle rate ($0.016/h; the free grant is worth only ≈ $1.6 at that rate) | ≈ $22 | **≈ $28** |

## Where the money would go if something went wrong

- **A scraper or uptime check that polls every few seconds** keeps the app
  awake around the clock: one app at the active rate is 730 h × $0.054 ≈ $39,
  so the bill goes from ≈ $6 to ≈ $40. This is why
  `/metrics` is off on Azure.
- **Forgetting to delete the resource group**: the registry keeps charging
  $5 a month on its own.
- **More replicas**: not allowed here anyway (`--max-replicas 1`, because of
  Litestream).

## Compared with the VM

The lecturer's VM (SWITCHengines) costs the same whether BikeShop runs or not,
and is shared with other services. On Azure you pay for what runs: the bill is
small because the app sleeps most of the time.
