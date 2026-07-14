#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUTPUT_DIR="${PROJECT_ROOT}/dist"
BUNDLE_NAME=""
IMAGE_REPO="${SIM_INFRA_IMAGE_REPO:-xcn-similarity}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/package_infra_bundle.sh [--output-dir <dir>] [--name <bundle-name>]

Behavior:
  - Packages only xcn-similarity infra Docker images.
  - Creates a runtime package started with: docker compose up -d
  - Uses fixed infra data paths under /data/infra.
  - Does not package MongoDB, MinIO, Milvus, or etcd data.
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

write_package_env() {
  local target_path="$1"
  cat > "${target_path}" <<EOF
MONGO_IMAGE=${IMAGE_REPO}/mongo:8.3
ETCD_IMAGE=${IMAGE_REPO}/etcd:v3.5.18
MINIO_IMAGE=${IMAGE_REPO}/minio:latest
MILVUS_IMAGE=${IMAGE_REPO}/milvus:v2.6.18
MILVUS_MINIO_ACCESS_KEY=minioadmin
MILVUS_MINIO_SECRET_KEY=minioadmin
EOF
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

Loads offline Docker images, prepares .env, creates /data/infra directories,
and starts xcn-similarity infra with docker compose up -d unless --no-start is used.
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

create_dir() {
  local dir_path="$1"
  if mkdir -p "${dir_path}" 2>/dev/null; then
    return 0
  fi
  echo "failed to create ${dir_path}; run install.sh as a user with permission for /data/infra" >&2
  exit 1
}

create_dir /data/infra/mongodb
create_dir /data/infra/mongodb_config
create_dir /data/infra/xcn-similarity-etcd
create_dir /data/infra/minio
create_dir /data/infra/minio_config
create_dir /data/infra/milvus

docker compose config --quiet

if [[ "${NO_START}" == "true" ]]; then
  echo "Install completed. Start manually with: docker compose up -d"
  exit 0
fi

docker compose up -d
INSTALL_EOF
}

write_package_readme() {
  local target_path="$1"
  cat > "${target_path}" <<'README_EOF'
# xcn-similarity infra offline package

Common commands:

```bash
./install.sh --no-start
docker compose up -d
docker compose down
docker compose ps
docker compose logs -f
```

Data paths:

- MongoDB: `/data/infra/mongodb`, `/data/infra/mongodb_config`
- etcd: `/data/infra/xcn-similarity-etcd`
- MinIO: `/data/infra/minio`, `/data/infra/minio_config`
- Milvus: `/data/infra/milvus`

Notes:

- `install.sh` loads Docker images and prepares `.env`.
- Docker services are started with `docker compose up -d`.
- Runtime data is not included in this package.
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
APP_VERSION="$(read_first_line VERSION)"
if [[ -z "${APP_VERSION}" ]]; then
  echo "VERSION file is empty" >&2
  exit 1
fi

IMAGES=(
  "${IMAGE_REPO}/mongo:8.3"
  "${IMAGE_REPO}/etcd:v3.5.18"
  "${IMAGE_REPO}/minio:latest"
  "${IMAGE_REPO}/milvus:v2.6.18"
)

for image_name in "${IMAGES[@]}"; do
  if ! image_exists "${image_name}"; then
    echo "required image not found: ${image_name}" >&2
    exit 1
  fi
done

if [[ -z "${BUNDLE_NAME}" ]]; then
  BUNDLE_NAME="xcn-similarity-infra-package-${APP_VERSION}-$(date +%Y%m%d-%H%M%S)"
fi

mkdir -p "${OUTPUT_DIR}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT
BUNDLE_ROOT_NAME="xcn-similarity-infra"
BUNDLE_DIR="${WORK_DIR}/${BUNDLE_ROOT_NAME}"
mkdir -p "${BUNDLE_DIR}/images"

copy_file "${PROJECT_ROOT}/VERSION" "${BUNDLE_DIR}/VERSION"
copy_file "${PROJECT_ROOT}/docker-compose.infra.yml" "${BUNDLE_DIR}/docker-compose.yml"
write_package_env "${BUNDLE_DIR}/.env.package"
write_install_script "${BUNDLE_DIR}/install.sh"
chmod +x "${BUNDLE_DIR}/install.sh"
if ! bash -n "${BUNDLE_DIR}/install.sh"; then
  echo "generated install.sh has a shell syntax error" >&2
  exit 1
fi
write_package_readme "${BUNDLE_DIR}/README.md"

IMAGE_ARCHIVE="${BUNDLE_DIR}/images/xcn-similarity-infra-images.tar"
echo "Saving Docker images to ${IMAGE_ARCHIVE}"
docker save -o "${IMAGE_ARCHIVE}" "${IMAGES[@]}"

{
  echo "package=${BUNDLE_NAME}"
  echo "created_at=$(date -Iseconds)"
  echo "app_version=${APP_VERSION}"
  echo "data_root=/data/infra"
  echo "include_runtime_data=false"
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
