#!/bin/sh
set -eu

# Reset only data owned by xcn-similarity. EMS source data and infra volumes are
# deliberately outside this script's scope.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
DEFAULT_APP_DIR=$(dirname "$SCRIPT_DIR")
APP_DIR=${XCN_SIM_APP_DIR:-$DEFAULT_APP_DIR}
MONGO_CONTAINER=${XCN_SIM_MONGO_CONTAINER:-xcn-similarity-mongodb}
MONGO_DATABASE=${XCN_SIM_MONGO_DATABASE:-xcn_similarity}
MILVUS_URL=${XCN_SIM_MILVUS_URL:-http://127.0.0.1:19530}
API_HEALTH_URL=${XCN_SIM_HEALTH_URL:-http://127.0.0.1:8010/health}

DRY_RUN=false
ASSUME_YES=false
INCLUDE_LOGS=false
NO_RESTART=false
STOPPED_CONTAINERS=""
RESET_STARTED=false

usage() {
    cat <<'EOF'
Usage: scripts/reset_xcn_similarity.sh [options]

Reset only xcn-similarity application-owned data:
  - MongoDB database: xcn_similarity
  - Milvus collections: document_chunks, log_body_chunks
  - Uploaded files: <app-dir>/logs/uploads

EMS source MongoDB (venus/EMS_MESSAGE_*), EMS MinIO objects, container images,
and infra data volumes are never deleted.

Options:
  --dry-run       Show current targets and counts without changing anything.
  --yes           Skip the interactive destructive-action confirmation.
  --include-logs  Also delete xcn-similarity runtime log files.
  --no-restart    Leave previously running app containers stopped after reset.
  --app-dir DIR   Application directory (default: parent of this script).
  -h, --help      Show this help.

Environment overrides:
  XCN_SIM_MONGO_CONTAINER, XCN_SIM_MILVUS_URL, XCN_SIM_HEALTH_URL
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

container_exists() {
    docker inspect "$1" >/dev/null 2>&1
}

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

restart_stopped_containers() {
    [ "$RESET_STARTED" = "true" ] || return 0
    [ "$NO_RESTART" = "false" ] || return 0
    [ -n "$STOPPED_CONTAINERS" ] || return 0
    echo "Restarting previously running app containers:$STOPPED_CONTAINERS"
    # shellcheck disable=SC2086
    docker start $STOPPED_CONTAINERS >/dev/null
    STOPPED_CONTAINERS=""
}

on_exit() {
    status=$?
    if [ "$status" -ne 0 ]; then
        restart_stopped_containers || true
    fi
    exit "$status"
}

milvus_request() {
    endpoint=$1
    payload=$2
    response=$(curl -fsS --max-time 30 \
        -H 'Content-Type: application/json' \
        -d "$payload" "$MILVUS_URL/v2/vectordb/$endpoint") || \
        die "Milvus request failed: $endpoint"
    compact=$(printf '%s' "$response" | tr -d '[:space:]')
    case "$compact" in
        *'"code":0'*|*'"code":200'*) printf '%s\n' "$response" ;;
        *) die "Milvus returned an error for $endpoint: $response" ;;
    esac
}

milvus_has_collection() {
    name=$1
    response=$(milvus_request collections/has "{\"collectionName\":\"$name\"}")
    compact=$(printf '%s' "$response" | tr -d '[:space:]')
    case "$compact" in
        *'"has":true'*|*'"data":true'*) return 0 ;;
        *) return 1 ;;
    esac
}

milvus_row_count() {
    name=$1
    if ! milvus_has_collection "$name"; then
        echo "absent"
        return
    fi
    response=$(milvus_request collections/get_stats "{\"collectionName\":\"$name\"}")
    compact=$(printf '%s' "$response" | tr -d '[:space:]')
    count=$(printf '%s' "$compact" | sed -n 's/.*"rowCount":\([0-9][0-9]*\).*/\1/p')
    [ -n "$count" ] || count="unknown"
    echo "$count"
}

mongo_summary() {
    docker exec "$MONGO_CONTAINER" mongosh --quiet --eval \
        'const d=db.getSiblingDB("xcn_similarity"); printjson(d.getCollectionNames().sort().map(n => ({name:n,count:d.getCollection(n).countDocuments({})})))'
}

safe_clear_directory() {
    target=$1
    expected_prefix=$2
    [ -d "$target" ] || return 0
    resolved=$(CDPATH= cd -- "$target" && pwd -P)
    case "$resolved" in
        "$expected_prefix"/*) ;;
        *) die "Refusing to clear unexpected path: $resolved" ;;
    esac
    find "$resolved" -mindepth 1 -delete
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --yes) ASSUME_YES=true ;;
        --include-logs) INCLUDE_LOGS=true ;;
        --no-restart) NO_RESTART=true ;;
        --app-dir)
            [ "$#" -ge 2 ] || die "--app-dir requires a directory"
            APP_DIR=$2
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1 (use --help)" ;;
    esac
    shift
done

command_exists docker || die "docker is required"
command_exists curl || die "curl is required"
[ -d "$APP_DIR" ] || die "Application directory not found: $APP_DIR"
APP_DIR=$(CDPATH= cd -- "$APP_DIR" && pwd -P)

# The reset is intentionally hard-limited to the product-owned database. This
# prevents a bad environment override from targeting EMS source databases.
[ "$MONGO_DATABASE" = "xcn_similarity" ] || \
    die "Refusing MongoDB database other than xcn_similarity: $MONGO_DATABASE"
container_exists "$MONGO_CONTAINER" || die "MongoDB container not found: $MONGO_CONTAINER"
docker exec "$MONGO_CONTAINER" mongosh --quiet --eval \
    'quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)' >/dev/null || \
    die "MongoDB ping failed"
milvus_request collections/list '{}' >/dev/null

echo "xcn-similarity reset targets"
echo "  app directory:       $APP_DIR"
echo "  MongoDB container:   $MONGO_CONTAINER"
echo "  MongoDB database:    $MONGO_DATABASE"
echo "  Milvus endpoint:     $MILVUS_URL"
echo "  Milvus collections:  document_chunks, log_body_chunks"
echo "  uploads:              $APP_DIR/logs/uploads"
echo "  runtime logs:         $INCLUDE_LOGS"
echo
echo "MongoDB current collections/counts:"
mongo_summary
echo "Milvus current row counts:"
echo "  document_chunks: $(milvus_row_count document_chunks)"
echo "  log_body_chunks: $(milvus_row_count log_body_chunks)"

if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN complete; no data was changed."
    exit 0
fi

if [ "$ASSUME_YES" != "true" ]; then
    echo
    echo "This permanently deletes the xcn-similarity targets listed above."
    printf '%s' 'Type RESET XCN-SIMILARITY to continue: '
    IFS= read -r answer
    [ "$answer" = "RESET XCN-SIMILARITY" ] || die "Confirmation did not match; cancelled"
fi

trap on_exit EXIT HUP INT TERM
RESET_STARTED=true

for container in xcn-similarity-api xcn-similarity-indexer; do
    if container_running "$container"; then
        STOPPED_CONTAINERS="$STOPPED_CONTAINERS $container"
    fi
done
if [ -n "$STOPPED_CONTAINERS" ]; then
    echo "Stopping app containers:$STOPPED_CONTAINERS"
    # shellcheck disable=SC2086
    docker stop $STOPPED_CONTAINERS >/dev/null
fi

for collection in document_chunks log_body_chunks; do
    if milvus_has_collection "$collection"; then
        echo "Dropping Milvus collection: $collection"
        milvus_request collections/drop "{\"collectionName\":\"$collection\"}" >/dev/null
    else
        echo "Milvus collection already absent: $collection"
    fi
done

echo "Dropping MongoDB database: $MONGO_DATABASE"
docker exec "$MONGO_CONTAINER" mongosh --quiet --eval \
    'const r=db.getSiblingDB("xcn_similarity").dropDatabase(); if (!r.ok) { printjson(r); quit(1) }' >/dev/null

echo "Clearing uploaded files"
safe_clear_directory "$APP_DIR/logs/uploads" "$APP_DIR/logs"

if [ "$INCLUDE_LOGS" = "true" ]; then
    echo "Clearing runtime log files"
    if [ -d "$APP_DIR/logs" ]; then
        find "$APP_DIR/logs" -mindepth 1 -maxdepth 1 ! -name uploads -delete
    fi
fi

restart_stopped_containers
RESET_STARTED=false
trap - EXIT HUP INT TERM

if [ "$NO_RESTART" = "false" ] && container_running xcn-similarity-api; then
    echo "Waiting for API health check"
    healthy=false
    attempt=1
    while [ "$attempt" -le 30 ]; do
        if curl -fsS --max-time 5 "$API_HEALTH_URL" >/dev/null 2>&1; then
            healthy=true
            break
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
    [ "$healthy" = "true" ] || die "API health check failed after reset: $API_HEALTH_URL"
fi

for collection in document_chunks log_body_chunks; do
    milvus_has_collection "$collection" && \
        die "Milvus collection still exists after reset: $collection"
done

remaining=$(docker exec "$MONGO_CONTAINER" mongosh --quiet --eval \
    'const d=db.getSiblingDB("xcn_similarity"); print(d.getCollectionNames().map(n => d.getCollection(n).countDocuments({})).reduce((a,b)=>a+b,0))' | tr -d '[:space:]')
[ "$remaining" = "0" ] || die "MongoDB contains $remaining rows after reset"

echo "xcn-similarity reset completed successfully."

