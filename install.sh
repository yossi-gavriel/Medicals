#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Drug Safety Engine — one-click installer
#
#   ./install.sh              # full bootstrap (env, build, migrate, seed, up)
#   ./install.sh local        # local dev mode (no Docker; requires Python 3.11+)
#   ./install.sh reset        # tear everything down and start clean
#   ./install.sh logs         # follow logs of the full stack
#   ./install.sh status       # show health of api / worker / outbox
#
# Idempotent: safe to re-run. Will not overwrite an existing .env.
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { printf "${BLUE}[install]${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}[ ok  ]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn ]${NC} %s\n" "$*"; }
die()   { printf "${RED}[fail ]${NC} %s\n" "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1 — please install it and re-run"
}

generate_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 -c "import secrets; print(secrets.token_hex(24))"
  fi
}

choose_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "neither 'docker compose' nor 'docker-compose' is available"
  fi
}

ensure_env_file() {
  if [[ -f .env ]]; then
    ok ".env already exists — keeping it"
    return
  fi
  log "creating .env from .env.example"
  cp .env.example .env

  local api_key
  api_key="$(generate_key)"
  local webhook_secret
  webhook_secret="$(generate_key)"

  # Inject generated secrets (BSD/GNU sed compatible)
  python3 - "$api_key" "$webhook_secret" <<'PY'
import pathlib, sys
api_key, webhook_secret = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
text = path.read_text()
replacements = {
    "API_KEYS=dev-local-key": f"API_KEYS={api_key}",
    "INTERNAL_API_KEYS=": f"INTERNAL_API_KEYS={api_key}",
    "WEBHOOK_SIGNING_SECRET=": f"WEBHOOK_SIGNING_SECRET={webhook_secret}",
}
for old, new in replacements.items():
    text = text.replace(old, new, 1)
path.write_text(text)
PY

  ok "generated random API key + webhook signing secret in .env"
  printf "${YELLOW}      API key:${NC} %s\n" "$api_key"
  printf "${YELLOW}      keep it private — used in 'X-API-Key' header${NC}\n"
}

wait_for_health() {
  local url="$1"
  local name="$2"
  local timeout="${3:-90}"
  local elapsed=0
  log "waiting for ${name} at ${url}"
  while ! curl --silent --fail --max-time 2 "$url" >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout )); then
      die "${name} did not become healthy within ${timeout}s"
    fi
  done
  ok "${name} is up"
}

cmd_docker_full() {
  require docker
  require curl
  require python3
  choose_compose

  ensure_env_file

  log "building images"
  "${COMPOSE[@]}" build

  log "starting infra (postgres, redis)"
  "${COMPOSE[@]}" up -d postgres redis

  log "running database migrations"
  "${COMPOSE[@]}" run --rm migrate

  log "seeding demo drugs and synonyms"
  "${COMPOSE[@]}" run --rm api python -m scripts.seed_drugs
  "${COMPOSE[@]}" run --rm api python -m scripts.seed_synonyms

  log "starting api, worker, outbox"
  "${COMPOSE[@]}" up -d api worker outbox

  wait_for_health "http://localhost:8000/health" "api"

  ok "stack is up"
  cat <<MSG

  ──────────────────────────────────────────────────────────────
  ${GREEN}Drug Safety Engine is ready${NC}

  API:        http://localhost:8000
  OpenAPI:    http://localhost:8000/docs
  Metrics:    http://localhost:8000/metrics
  Readiness:  http://localhost:8000/ready

  Useful:
    ./install.sh logs       follow logs (all services)
    ./install.sh status     health of api/worker/outbox
    ./install.sh reset      destroy everything and reinstall

  Submit a document for async classification:
    curl -X POST http://localhost:8000/v1/classifications \\
      -H 'Content-Type: application/json' \\
      -H "X-API-Key: \$(grep ^API_KEYS .env | cut -d= -f2)" \\
      -d '{"procedure_code":"arthroscopy_knee","document_text":"בוצעה ארתרוסקופיה ברך ימין"}'

MSG
}

cmd_local() {
  require python3
  require curl
  log "creating local virtualenv (.venv)"
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate

  log "installing python dependencies"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -e ".[dev]"

  ensure_env_file

  if [[ -z "${DATABASE_URL:-}" ]]; then
    warn "Local mode assumes Postgres + Redis are reachable per your .env"
    warn "Tip: run 'docker compose up -d postgres redis' to provide them"
  fi

  log "applying migrations"
  alembic upgrade head

  log "seeding demo data"
  python -m scripts.seed_drugs
  python -m scripts.seed_synonyms

  ok "local install ready"
  cat <<MSG

  Start the API:        make dev
  Start the worker:     make worker
  Start the outbox:     make outbox

MSG
}

cmd_reset() {
  choose_compose
  warn "this will delete all containers AND volumes (postgres, redis, document storage)"
  read -r -p "type 'yes' to continue: " confirm
  [[ "$confirm" == "yes" ]] || die "aborted"
  "${COMPOSE[@]}" down -v
  ok "stack reset — run ./install.sh to bootstrap again"
}

cmd_logs() {
  choose_compose
  "${COMPOSE[@]}" logs -f --tail=200
}

cmd_status() {
  choose_compose
  "${COMPOSE[@]}" ps
  printf "\n"
  curl --silent --max-time 3 http://localhost:8000/ready || warn "api /ready not reachable"
  printf "\n"
}

main() {
  local cmd="${1:-docker}"
  case "$cmd" in
    docker|"") cmd_docker_full ;;
    local)     cmd_local ;;
    reset)     cmd_reset ;;
    logs)      cmd_logs ;;
    status)    cmd_status ;;
    -h|--help|help)
      sed -n '2,15p' "$0"
      ;;
    *)
      die "unknown command: $cmd  (try: docker | local | reset | logs | status)"
      ;;
  esac
}

main "$@"
