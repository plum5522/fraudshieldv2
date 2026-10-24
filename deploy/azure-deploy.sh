#!/usr/bin/env bash
# Deploy FraudShield v2 to Azure: Container Apps (API) + PostgreSQL Flexible Server (data).
#
# Run from the repo root in Azure Cloud Shell (Bash), which has `az` and is already logged in:
#   git clone https://github.com/plum5522/fraudshieldv2 && cd fraudshieldv2
#   bash deploy/azure-deploy.sh
#
# Safe to re-run: existing resources are reused, secrets are kept in deploy/.azure.env
# (gitignored). The image is built in Azure (ACR Tasks), so no local Docker is needed.
set -euo pipefail

STATE=deploy/.azure.env
[ -f "$STATE" ] && source "$STATE"

RG=${RG:-fraudshield-rg}
LOC=${LOC:-centralindia}
APP=${APP:-fraudshield-api}
CAE=${CAE:-fraudshield-env}
PG=${PG:-fraudshield-db-$RANDOM$RANDOM}           # must be globally unique
PG_USER=${PG_USER:-fsadmin}
PG_PASS=${PG_PASS:-Fs$(openssl rand -hex 16)}       # upper + lower + digits, URL-safe
REPORTER_SECRET=${REPORTER_SECRET:-$(openssl rand -hex 32)}

cat > "$STATE" <<EOF
RG=$RG
LOC=$LOC
APP=$APP
CAE=$CAE
PG=$PG
PG_USER=$PG_USER
PG_PASS=$PG_PASS
REPORTER_SECRET=$REPORTER_SECRET
EOF
chmod 600 "$STATE"

step() { printf '\n==> %s\n' "$1"; }

step "Azure CLI extension and providers"
az extension add --name containerapp --upgrade --only-show-errors
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL Microsoft.ContainerRegistry; do
  az provider register --namespace "$p" --only-show-errors >/dev/null
done

step "Resource group $RG ($LOC)"
az group create -n "$RG" -l "$LOC" --only-show-errors -o none

step "PostgreSQL Flexible Server $PG (Burstable B1ms, Postgres 16) - takes ~5 min"
if ! az postgres flexible-server show -g "$RG" -n "$PG" -o none 2>/dev/null; then
  az postgres flexible-server create -g "$RG" -n "$PG" -l "$LOC" \
    --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
    --admin-user "$PG_USER" --admin-password "$PG_PASS" \
    --public-access 0.0.0.0 --yes --only-show-errors -o none
  # 0.0.0.0 = allow connections from Azure services only (our container), not the internet.
fi
step "Database 'fraudshield' on $PG"
if ! az postgres flexible-server db show -g "$RG" --server-name "$PG" --name fraudshield -o none 2>/dev/null; then
  az postgres flexible-server db create -g "$RG" --server-name "$PG" --name fraudshield --only-show-errors -o none
fi

DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@${PG}.postgres.database.azure.com:5432/fraudshield?sslmode=require"

step "Build the image in Azure and create the Container App - takes ~5 min"
# First revision boots on a temporary SQLite file so it is healthy; the next step switches
# it to Postgres with secrets.
az containerapp up -n "$APP" -g "$RG" -l "$LOC" --environment "$CAE" \
  --source . --ingress external --target-port 8000 \
  --env-vars DATABASE_URL=sqlite:////tmp/boot.db --only-show-errors -o none

step "Secrets and production settings"
az containerapp secret set -n "$APP" -g "$RG" \
  --secrets db-url="$DB_URL" reporter-secret="$REPORTER_SECRET" --only-show-errors -o none
# max-replicas 1: the rate limiter keeps its counts in memory (one instance = correct counts).
# min-replicas 0: scales to zero when idle (near-free), first request after idle is slower.
az containerapp update -n "$APP" -g "$RG" \
  --set-env-vars DATABASE_URL=secretref:db-url REPORTER_SECRET=secretref:reporter-secret \
  --min-replicas 0 --max-replicas 1 --only-show-errors -o none

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)

step "Waiting for the API to answer"
for i in $(seq 1 30); do
  if curl -sf "https://$FQDN/v1/health" >/dev/null; then break; fi
  sleep 5
done
curl -s "https://$FQDN/v1/health"; echo

cat <<EOF

Done.
  API:   https://$FQDN
  Docs:  https://$FQDN/docs

Secrets are saved in $STATE (never commit it).
To save credits when not demoing:   az postgres flexible-server stop -g $RG -n $PG
Start it again before a demo:       az postgres flexible-server start -g $RG -n $PG
Redeploy after a code change:       az containerapp up -n $APP -g $RG --source .
Delete everything:                  az group delete -n $RG
EOF
