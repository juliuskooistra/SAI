#!/bin/sh
# How the API container starts (SPEC §10).
#
#   APP_MODE=api (default)  The API only. The VM set-up: the worker runs in
#                           its own container and the database is on a volume.
#   APP_MODE=all            Azure Container Apps: the container keeps no files,
#                           so Litestream restores the database from Azure Blob
#                           Storage, then runs the API and the worker and
#                           copies every change back (SPEC §10.2).
set -eu

DB_DIR="${BIKESHOP_DATA_DIR:-/app/api/data}"
WORKERS="${UVICORN_WORKERS:-4}"

# The 4 uvicorn workers each count their own share of the metrics; with this
# folder set they write to files there and /metrics adds them up (SPEC §10.3).
# Emptied at every start, so old processes' numbers don't linger.
prepare_metrics() {
    export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus}"
    rm -rf "$PROMETHEUS_MULTIPROC_DIR"
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
}

run_api() {
    exec uvicorn api.expose_api:app --host 0.0.0.0 --port 8000 --workers "$WORKERS"
}

case "${1:-${APP_MODE:-api}}" in
  api)
    prepare_metrics
    run_api
    ;;

  children)
    # Started by Litestream (below): the worker in the background, the API
    # in the foreground. When the API stops, Litestream and the container stop.
    python -m scripts.worker &
    run_api
    ;;

  all)
    : "${LITESTREAM_AZURE_ACCOUNT_NAME:?Set LITESTREAM_AZURE_ACCOUNT_NAME}"
    : "${LITESTREAM_AZURE_ACCOUNT_KEY:?Set LITESTREAM_AZURE_ACCOUNT_KEY}"
    : "${LITESTREAM_AZURE_CONTAINER:?Set LITESTREAM_AZURE_CONTAINER}"
    export BIKESHOP_DATA_DIR="$DB_DIR"
    # Where in the blob container this copy's database lives: production and
    # staging must never share a path (SPEC §10.2)
    export LITESTREAM_PATH="${LITESTREAM_PATH:-bikeshop}"
    export LITESTREAM_AZURE_ENDPOINT="${LITESTREAM_AZURE_ENDPOINT:-https://${LITESTREAM_AZURE_ACCOUNT_NAME}.blob.core.windows.net/}"
    mkdir -p "$DB_DIR"

    echo "litestream: restoring $DB_DIR/bikeshop.db (if a copy exists)"
    litestream restore -config /app/litestream.yml -if-db-not-exists -if-replica-exists "$DB_DIR/bikeshop.db"

    # Create the tables once, before several processes start at the same time
    python -c "from api.database import init_database; init_database()"
    if [ "${SEED_ON_START:-0}" = "1" ]; then
        python -m scripts.seed   # only adds what's missing
    fi

    prepare_metrics
    echo "litestream: replicating, starting API and worker"
    exec litestream replicate -config /app/litestream.yml -exec "sh /app/scripts/start.sh children"
    ;;

  *)
    echo "Unknown APP_MODE '${APP_MODE:-}': use api or all" >&2
    exit 1
    ;;
esac
