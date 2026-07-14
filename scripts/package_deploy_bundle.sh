#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUTPUT_DIR="${PROJECT_ROOT}/dist"
BUNDLE_NAME=""
INCLUDE_ENV="true"
API_IMAGE_REPO="${SIM_IMAGE_REPO:-xcn-similarity}"
API_IMAGE_TAG=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/package_deploy_bundle.sh [--output-dir <dir>] [--name <bundle-name>] [--no-env]

Behavior:
  - Uses VERSION as the default SIM_IMAGE_TAG.
  - Pins the packaged API image as the runtime default via SIM_RUNTIME_IMAGE.
  - Packages Docker images already present on this host.
  - Creates a runtime package started with: docker compose up -d
  - install.sh starts API mode only.
  - Does not expose app/tools/vendor source directories in the package.
  - Excludes bundled Kafka service/image settings.
  - Does not package models, Milvus/MinIO data, MongoDB data, or logs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --output-dir=*)
      OUTPUT_DIR="${1#*=}"
      shift
      ;;
    --name)
      BUNDLE_NAME="$2"
      shift 2
      ;;
    --name=*)
      BUNDLE_NAME="${1#*=}"
      shift
      ;;
    --no-env)
      INCLUDE_ENV="false"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command not found: ${command_name}" >&2
    exit 1
  fi
}

read_first_line() {
  local file_path="$1"
  tr -d '\r' < "${file_path}" | head -n 1
}

image_exists() {
  docker image inspect "$1" >/dev/null 2>&1
}

copy_file() {
  local source_path="$1"
  local target_path="$2"
  mkdir -p "$(dirname "${target_path}")"
  cp "${source_path}" "${target_path}"
}

env_value() {
  local key="$1"
  local file_path="$2"
  if [[ ! -f "${file_path}" ]]; then
    return 1
  fi
  grep -E "^${key}=" "${file_path}" | tail -n 1 | cut -d '=' -f 2- || true
}

write_package_env() {
  local target_path="$1"
  local source_env="${PROJECT_ROOT}/.env"
  {
    echo "SIM_IMAGE_REPO=${API_IMAGE_REPO}"
    echo "SIM_IMAGE_TAG=${API_IMAGE_TAG}"
    echo "COMPOSE_PROFILES="
    echo "SIM_PACKAGE_MODE=api"
    echo "SIM_DOCKER_NETWORK=xcn-similarity-infra_default"
    echo "SIM_MILVUS_URL=http://milvus:19530"
    echo "SIM_CATALOG_MONGO_URI=mongodb://mongodb:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000"
    echo "SIM_MODELS_VOLUME=/data/models"
    echo "SIM_MILVUS_MINIO_VOLUME=/data/infra/minio"
    echo "SIM_EMBEDDING_MODEL_PATH=/models/upskyy_bge_m3_korean"
    if [[ "${INCLUDE_ENV}" == "true" && -f "${source_env}" ]]; then
      while IFS= read -r line || [[ -n "${line}" ]]; do
        case "${line}" in
          ""|\#*) continue ;;
          SIM_IMAGE_REPO=*|SIM_IMAGE_TAG=*|COMPOSE_PROFILES=*|SIM_PACKAGE_MODE=*|KAFKA_IMAGE=*|SIM_KAFKA_*) continue ;;
          *) echo "${line}" ;;
        esac
      done < "${source_env}"
    fi
  } > "${target_path}"
}

write_runtime_compose() {
  local source_path="$1"
  local target_path="$2"
  awk '
    /^  indexer:/ { skip = 1; next }
    /^  kafka:/ { skip = 1; next }
    skip && /^  [A-Za-z0-9_-]+:/ { skip = 0 }
    skip { next }
    /KAFKA_IMAGE/ { next }
    /SIM_KAFKA_/ { next }
    { print }
  ' "${source_path}" > "${target_path}"
  sed -i -E \
    "s|^([[:space:]]*)image:.*SIM_IMAGE_REPO.*$|\1image: \${SIM_RUNTIME_IMAGE:-${API_IMAGE_REPO}/api:${API_IMAGE_TAG}}|" \
    "${target_path}"
  cat >> "${target_path}" <<'COMPOSE_NETWORK_EOF'

networks:
  default:
    external: true
    name: ${SIM_DOCKER_NETWORK:-xcn-similarity-infra_default}
COMPOSE_NETWORK_EOF
}

write_install_script() {
  local target_path="$1"
  cat > "${target_path}" <<'INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail

NO_START="false"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--no-start]

Loads the API image, prepares .env, and starts xcn-similarity API unless --no-start is used.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start)
      NO_START="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_ROOT}"

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required" >&2
  exit 1
fi

if compgen -G "images/*.tar" >/dev/null; then
  for image_archive in images/*.tar; do
    echo "Loading Docker image archive: ${image_archive}"
    docker load -i "${image_archive}"
  done
else
  echo "no image archive found under ${PROJECT_ROOT}/images" >&2
  exit 1
fi

if [[ -f ".env.package" && ! -f ".env" ]]; then
  cp ".env.package" ".env"
fi
touch ".env"

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp_file
  tmp_file="$(mktemp)"
  if grep -qE "^${key}=" ".env"; then
    sed -E "s|^${key}=.*|${key}=${value}|" ".env" > "${tmp_file}"
  else
    cat ".env" > "${tmp_file}"
    printf '%s=%s\n' "${key}" "${value}" >> "${tmp_file}"
  fi
  mv "${tmp_file}" ".env"
}

set_env_value "COMPOSE_PROFILES" ""
set_env_value "SIM_PACKAGE_MODE" "api"

mkdir -p logs

docker compose config --quiet

if [[ "${NO_START}" == "true" ]]; then
  echo "Install completed for API mode. Start manually with: docker compose up -d"
  exit 0
fi

echo "Starting package API mode"
docker compose up -d
INSTALL_EOF
}

write_package_readme() {
  local target_path="$1"
  cat > "${target_path}" <<'README_EOF'
# xcn-similarity offline package

Common commands:

```bash
./install.sh --no-start
docker compose up -d
docker compose down
docker compose ps
docker compose logs -f
```

Notes:

- `install.sh` loads Docker images and prepares `.env`.
- Services are started with `docker compose up -d`.
- This package starts the API service only.
- App source directories are not included in the extracted install tree; runtime code is inside the Docker image.
- Models, Milvus/MinIO data, MongoDB data, and logs are not included. Configure their host paths/endpoints in `.env`.
- The package expects the infra package network to exist. Default network: `xcn-similarity-infra_default`.
README_EOF
}

require_command docker
require_command tar
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

if [[ ! -f VERSION ]]; then
  echo "VERSION file is missing" >&2
  exit 1
fi
API_IMAGE_TAG="$(read_first_line VERSION)"
if [[ -z "${API_IMAGE_TAG}" ]]; then
  echo "VERSION file is empty" >&2
  exit 1
fi

if [[ -f ".env" ]]; then
  env_repo="$(env_value SIM_IMAGE_REPO .env || true)"
  if [[ -n "${env_repo}" ]]; then
    API_IMAGE_REPO="${env_repo}"
  fi
fi

API_IMAGE="${API_IMAGE_REPO}/api:${API_IMAGE_TAG}"
if ! image_exists "${API_IMAGE}"; then
  echo "required image not found: ${API_IMAGE}" >&2
  exit 1
fi

IMAGES=("${API_IMAGE}")

if [[ -z "${BUNDLE_NAME}" ]]; then
  BUNDLE_NAME="xcn-similarity-package-${API_IMAGE_TAG}-$(date +%Y%m%d-%H%M%S)"
fi

mkdir -p "${OUTPUT_DIR}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT
BUNDLE_ROOT_NAME="xcn-similarity"
BUNDLE_DIR="${WORK_DIR}/${BUNDLE_ROOT_NAME}"
mkdir -p "${BUNDLE_DIR}/images"

copy_file "${PROJECT_ROOT}/VERSION" "${BUNDLE_DIR}/VERSION"
copy_file "${PROJECT_ROOT}/.env.example" "${BUNDLE_DIR}/.env.example"
if [[ -f "${PROJECT_ROOT}/.env.external.example" ]]; then
  copy_file "${PROJECT_ROOT}/.env.external.example" "${BUNDLE_DIR}/.env.external.example"
fi
if [[ -f "${PROJECT_ROOT}/scripts/reset_xcn_similarity.sh" ]]; then
  copy_file "${PROJECT_ROOT}/scripts/reset_xcn_similarity.sh" "${BUNDLE_DIR}/scripts/reset_xcn_similarity.sh"
  chmod +x "${BUNDLE_DIR}/scripts/reset_xcn_similarity.sh"
fi
write_runtime_compose "${PROJECT_ROOT}/docker-compose.app.yml" "${BUNDLE_DIR}/docker-compose.yml"
find "${BUNDLE_DIR}" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
find "${BUNDLE_DIR}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

write_package_env "${BUNDLE_DIR}/.env.package"
write_install_script "${BUNDLE_DIR}/install.sh"
chmod +x "${BUNDLE_DIR}/install.sh"
if ! bash -n "${BUNDLE_DIR}/install.sh"; then
  echo "generated install.sh has a shell syntax error" >&2
  exit 1
fi
write_package_readme "${BUNDLE_DIR}/README.md"

IMAGE_ARCHIVE="${BUNDLE_DIR}/images/xcn-similarity-images.tar"
echo "Saving Docker images to ${IMAGE_ARCHIVE}"
docker save -o "${IMAGE_ARCHIVE}" "${IMAGES[@]}"

{
  echo "package=${BUNDLE_NAME}"
  echo "created_at=$(date -Iseconds)"
  echo "app_version=${API_IMAGE_TAG}"
  echo "runtime_modes=api"
  echo "include_env=${INCLUDE_ENV}"
  echo "include_kafka=false"
  echo "include_models=false"
  echo "include_infra_data=false"
  echo "images:"
  printf '  - %s\n' "${IMAGES[@]}"
} > "${BUNDLE_DIR}/MANIFEST.txt"

ARCHIVE_PATH="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"
tar -C "${WORK_DIR}" -czf "${ARCHIVE_PATH}" "${BUNDLE_ROOT_NAME}"

echo "Created package: ${ARCHIVE_PATH}"
echo "Install on target:"
echo "  tar -xzf $(basename "${ARCHIVE_PATH}")"
echo "  cd ${BUNDLE_ROOT_NAME}"
echo "  ./install.sh --no-start"
echo "  docker compose up -d"
