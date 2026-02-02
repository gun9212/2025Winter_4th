#!/bin/bash
#
# Full Cycle Test Script for Council-AI
#
# This script performs:
# 1. Reset: Clean data and restart containers
# 2. Ingest: Sync files from Google Drive and run pipeline
# 3. Verify: Run E2E tests against the API
#
# Usage:
#   ./scripts/run_full_cycle_test.sh [--skip-reset] [--skip-ingest]
#
# Prerequisites:
#   - Docker & Docker Compose installed
#   - .env file with GOOGLE_DRIVE_FOLDER_ID (for rclone sync)
#   - rclone configured with 'gdrive' remote (optional)
#

set -e  # Exit on error

# =============================================================================
# Configuration
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BACKEND_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
SKIP_RESET=false
SKIP_INGEST=false

for arg in "$@"; do
    case $arg in
        --skip-reset)
            SKIP_RESET=true
            shift
            ;;
        --skip-ingest)
            SKIP_INGEST=true
            shift
            ;;
    esac
done

# =============================================================================
# Load Environment Variables from .env
# =============================================================================
load_env() {
    local env_file="$PROJECT_ROOT/.env"

    if [ -f "$env_file" ]; then
        log_info "Loading environment from $env_file"
        # Export variables from .env (ignore comments and empty lines)
        set -a
        source <(grep -v '^#' "$env_file" | grep -v '^$' | sed 's/\r$//')
        set +a
    else
        env_file="$BACKEND_DIR/.env"
        if [ -f "$env_file" ]; then
            log_info "Loading environment from $env_file"
            set -a
            source <(grep -v '^#' "$env_file" | grep -v '^$' | sed 's/\r$//')
            set +a
        else
            log_warn "No .env file found. Some features may not work."
            log_warn "Expected locations: $PROJECT_ROOT/.env or $BACKEND_DIR/.env"
        fi
    fi
}

# =============================================================================
# Helper Functions
# =============================================================================
log_step() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}[STEP] $1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

wait_for_postgres() {
    log_info "Waiting for PostgreSQL to be ready..."

    for i in {1..30}; do
        if docker compose exec -T db pg_isready -U ${POSTGRES_USER:-myuser} > /dev/null 2>&1; then
            echo ""
            log_info "PostgreSQL is ready!"
            return 0
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 30 ]; then
            echo ""
            log_error "PostgreSQL failed to start after 30 seconds"
            exit 1
        fi
    done
}

wait_for_redis() {
    log_info "Waiting for Redis to be ready..."

    for i in {1..15}; do
        if docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
            echo ""
            log_info "Redis is ready!"
            return 0
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 15 ]; then
            echo ""
            log_error "Redis failed to start after 15 seconds"
            exit 1
        fi
    done
}

wait_for_api() {
    log_info "Waiting for API server to be ready..."

    for i in {1..60}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo ""
            log_info "API server is ready!"
            return 0
        fi
        echo -n "."
        sleep 2
        if [ "$i" -eq 60 ]; then
            echo ""
            log_error "API server failed to start after 120 seconds"
            exit 1
        fi
    done
}

# Docker exec wrapper for running Python commands inside backend container
run_in_container() {
    docker compose exec -T backend "$@"
}

# =============================================================================
# Pre-flight Checks
# =============================================================================
log_step "0. PRE-FLIGHT CHECKS"

# Load environment variables first (before using log functions in load_env)
cd "$PROJECT_ROOT"

# Check if .env exists and load it
ENV_FILE=""
if [ -f "$PROJECT_ROOT/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/.env"
elif [ -f "$BACKEND_DIR/.env" ]; then
    ENV_FILE="$BACKEND_DIR/.env"
fi

if [ -n "$ENV_FILE" ]; then
    log_info "Loading environment from $ENV_FILE"
    set -a
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/\r$//')
    set +a
else
    log_warn "No .env file found!"
    log_warn "Expected: $PROJECT_ROOT/.env or $BACKEND_DIR/.env"
    log_warn "Some features (like Google Drive sync) will be skipped."
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker compose version &> /dev/null; then
    log_error "Docker Compose is not available. Please install Docker Compose."
    exit 1
fi

log_info "Docker and Docker Compose are available."

# =============================================================================
# Step 1: Reset (Clean data and restart containers)
# =============================================================================
if [ "$SKIP_RESET" = false ]; then
    log_step "1. RESET - Cleaning data and restarting containers"

    cd "$PROJECT_ROOT"

    # Clean data directories using Docker (avoids permission issues)
    # Docker-created files are owned by root, so we use a container to delete them
    log_info "Cleaning data directories via Docker..."
    docker compose run --rm --entrypoint sh backend -c \
        "rm -rf /app/data/raw/* /app/data/source_documents/* 2>/dev/null; \
         mkdir -p /app/data/raw /app/data/source_documents" \
        2>/dev/null || log_warn "Data cleanup skipped (containers may not exist yet)"

    # Stop containers and remove volumes (this cleans DB data)
    log_info "Stopping containers and removing volumes..."
    docker compose down -v 2>/dev/null || true

    # Start fresh containers
    log_info "Starting fresh containers..."
    docker compose up -d

    # Wait for services
    wait_for_postgres
    wait_for_redis

    # Ensure data directories exist in container
    log_info "Ensuring data directories exist..."
    docker compose exec -T backend mkdir -p /app/data/raw /app/data/source_documents 2>/dev/null || true

    # Run migrations (if using alembic)
    log_info "Running database migrations..."
    if [ -f "$BACKEND_DIR/alembic.ini" ]; then
        docker compose exec -T backend alembic upgrade head 2>/dev/null || \
            log_warn "Alembic migration skipped (may already be at head)"
    fi

    log_info "Reset complete!"
else
    log_step "1. RESET - Skipped (--skip-reset)"
fi

# =============================================================================
# Step 2: Ingest (Sync and process documents)
# =============================================================================
if [ "$SKIP_INGEST" = false ]; then
    log_step "2. INGEST - Syncing and processing documents"

    cd "$PROJECT_ROOT"

    # Create data directory if needed
    mkdir -p data/source_documents

    # Sync from Google Drive using rclone
    log_info "Checking Google Drive sync configuration..."

    if [ -z "$GOOGLE_DRIVE_FOLDER_ID" ]; then
        echo ""
        log_warn "=============================================="
        log_warn "GOOGLE_DRIVE_FOLDER_ID is not set!"
        log_warn "=============================================="
        log_warn ""
        log_warn "To enable Google Drive sync, add this to your .env file:"
        log_warn "  GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here"
        log_warn ""
        log_warn "You can find the folder ID in the Google Drive URL:"
        log_warn "  https://drive.google.com/drive/folders/<FOLDER_ID>"
        log_warn ""
        log_warn "Skipping Google Drive sync. Pipeline will process existing files."
        echo ""
    elif ! command -v rclone &> /dev/null; then
        log_warn "rclone is not installed. Skipping Google Drive sync."
        log_warn "Install rclone: https://rclone.org/install/"
    elif ! rclone listremotes 2>/dev/null | grep -q "gdrive:"; then
        log_warn "rclone 'gdrive' remote is not configured."
        log_warn "Configure with: rclone config"
        log_warn "Skipping Google Drive sync."
    else
        log_info "Syncing files from Google Drive (Folder ID: ${GOOGLE_DRIVE_FOLDER_ID:0:10}...)"
        rclone sync "gdrive:$GOOGLE_DRIVE_FOLDER_ID" data/source_documents \
            --drive-export-formats docx,xlsx,pptx,pdf \
            --exclude "*.gform" \
            --progress || log_warn "rclone sync completed with warnings"
        log_info "Google Drive sync complete!"
    fi

    # Run pipeline using Python code INSIDE the backend container
    log_info "Running ingestion pipeline inside Docker container..."
    cd "$PROJECT_ROOT"

    # Run each pipeline step inside the backend container
    log_info "Running Step 1: Ingest..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step ingest || \
        log_warn "Ingest step completed with warnings"

    log_info "Running Step 2: Classify..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step classify || \
        log_warn "Classify step completed with warnings"

    log_info "Running Step 3: Parse..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step parse || \
        log_warn "Parse step completed with warnings"

    log_info "Running Step 4: Preprocess..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step preprocess || \
        log_warn "Preprocess step completed with warnings"

    log_info "Running Step 5: Chunk..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step chunk || \
        log_warn "Chunk step completed with warnings"

    log_info "Running Step 6: Enrich..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step enrich || \
        log_warn "Enrich step completed with warnings"

    log_info "Running Step 7: Embed..."
    docker compose exec -T backend python -m scripts.pipeline_runner --step embed || \
        log_warn "Embed step completed with warnings"

    # Show pipeline stats
    log_info "Pipeline Statistics:"
    docker compose exec -T backend python -m scripts.pipeline_runner --step stats

    log_info "Ingestion pipeline complete!"
else
    log_step "2. INGEST - Skipped (--skip-ingest)"
fi

# =============================================================================
# Step 3: Verify (Run E2E tests)
# =============================================================================
log_step "3. VERIFY - Running E2E tests"

cd "$PROJECT_ROOT"

# Wait for API to be ready
wait_for_api

# Run E2E test scenarios inside the backend container
log_info "Running E2E test scenarios..."
docker compose exec -T backend python tests/test_e2e_scenarios.py
TEST_EXIT_CODE=$?

# Check exit code
if [ $TEST_EXIT_CODE -eq 0 ]; then
    log_info "All E2E tests passed!"
else
    log_error "Some E2E tests failed!"
    exit 1
fi

# =============================================================================
# Summary
# =============================================================================
log_step "COMPLETE - Full Cycle Test Finished"

echo -e "${GREEN}"
echo "========================================"
echo "  Full Cycle Test Complete!"
echo "========================================"
echo -e "${NC}"

# Show final stats
log_info "Checking final pipeline stats..."
docker compose exec -T backend python -m scripts.pipeline_runner --step stats

echo ""
log_info "Useful commands:"
echo "  docker compose logs -f backend    # View backend logs"
echo "  docker compose exec backend bash  # Enter backend container"
echo "  docker compose ps                 # Check container status"
echo ""
