#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_x86_64}"
REQUIREMENTS_FILE="${LAMBDA_REQUIREMENTS_FILE:-${ROOT_DIR}/requirements.txt}"

BUILD_DIR="${ROOT_DIR}/build/lambda/medical-classifier"
DIST_DIR="${ROOT_DIR}/infra/serverless/build"
ZIP_PATH="${DIST_DIR}/medical-classifier-lambda.zip"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

"${PYTHON_BIN}" -m pip install \
  --requirement "${REQUIREMENTS_FILE}" \
  --target "${BUILD_DIR}" \
  --platform "${TARGET_PLATFORM}" \
  --implementation cp \
  --python-version "${PYTHON_VERSION}" \
  --only-binary=:all: \
  --upgrade

rsync -a \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  "${ROOT_DIR}/app/" "${BUILD_DIR}/app/"

mkdir -p "${BUILD_DIR}/data"
rsync -a \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  "${ROOT_DIR}/data/procedure_definitions/" "${BUILD_DIR}/data/procedure_definitions/"

find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type f -name "*.pyc" -delete

(
  cd "${BUILD_DIR}"
  zip -qr "${ZIP_PATH}" .
)

echo "Created ${ZIP_PATH}"

