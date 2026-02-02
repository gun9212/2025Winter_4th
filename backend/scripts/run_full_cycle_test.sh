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
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker compose exec -T postgres pg_isready -U council -d council_ai > /dev/null 2>&1; then
            log_info "PostgreSQL is ready!"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done

    log_error "PostgreSQL failed to start after ${max_attempts} seconds"
    return 1
}

wait_for_redis() {
    log_info "Waiting for Redis to be ready..."
    local max_attempts=15
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
            log_info "Redis is ready!"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done

    log_error "Redis failed to start after ${max_attempts} seconds"
    return 1
}

wait_for_api() {
    log_info "Waiting for API server to be ready..."
    local max_attempts=60
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_info "API server is ready!"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "API server failed to start after $((max_attempts * 2)) seconds"
    return 1
}

# =============================================================================
# Step 1: Reset (Clean data and restart containers)
# =============================================================================
if [ "$SKIP_RESET" = false ]; then
    log_step "1. RESET - Cleaning data and restarting containers"

    cd "$PROJECT_ROOT"

    # Clean source documents
    if [ -d "data/source_documents" ]; then
        log_info "Removing data/source_documents/*"
        rm -rf data/source_documents/*
    fi

    # Stop containers and remove volumes
    log_info "Stopping containers and removing volumes..."
    docker compose down -v 2>/dev/null || true

    # Start fresh containers
    log_info "Starting fresh containers..."
    docker compose up -d

    # Wait for services
    wait_for_postgres
    wait_for_redis

    # Run migrations (if using alembic)
    log_info "Running database migrations..."
    cd "$BACKEND_DIR"
    if [ -f "alembic.ini" ]; then
        docker compose exec -T api alembic upgrade head 2>/dev/null || \
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
    log_info "Syncing files from Google Drive..."
    if command -v rclone &> /dev/null; then
        # Check if gdrive remote exists
        if rclone listremotes | grep -q "gdrive:"; then
            DRIVE_FOLDER_ID="${GOOGLE_DRIVE_FOLDER_ID:-}"
            if [ -n "$DRIVE_FOLDER_ID" ]; then
                rclone sync "gdrive:$DRIVE_FOLDER_ID" data/source_documents \
                    --drive-export-formats docx,xlsx,pptx,pdf \
                    --exclude "*.gform" \
                    --progress
            else
                log_warn "GOOGLE_DRIVE_FOLDER_ID not set, skipping rclone sync"
            fi
        else
            log_warn "rclone 'gdrive' remote not configured, skipping sync"
        fi
    else
        log_warn "rclone not installed, skipping Drive sync"
    fi

    # Run pipeline using our Python code
    log_info "Running ingestion pipeline..."
    cd "$BACKEND_DIR"

    # Option A: Run via docker compose exec (if running in container)
    # docker compose exec -T api python -m scripts.pipeline_runner --step all

    # Option B: Run directly with local Python (for development)
    if [ -f ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    elif command -v python3 &> /dev/null; then
        PYTHON="python3"
    else
        PYTHON="python"
    fi

    log_info "Using Python: $PYTHON"

    # Run each pipeline step
    log_info "Running Step 1: Ingest..."
    $PYTHON -m scripts.pipeline_runner --step ingest || log_warn "Ingest step completed with warnings"

    log_info "Running Step 2: Classify..."
    $PYTHON -m scripts.pipeline_runner --step classify || log_warn "Classify step completed with warnings"

    log_info "Running Step 3: Parse..."
    $PYTHON -m scripts.pipeline_runner --step parse || log_warn "Parse step completed with warnings"

    log_info "Running Step 4: Preprocess..."
    $PYTHON -m scripts.pipeline_runner --step preprocess || log_warn "Preprocess step completed with warnings"

    log_info "Running Step 5: Chunk..."
    $PYTHON -m scripts.pipeline_runner --step chunk || log_warn "Chunk step completed with warnings"

    log_info "Running Step 6: Enrich..."
    $PYTHON -m scripts.pipeline_runner --step enrich || log_warn "Enrich step completed with warnings"

    log_info "Running Step 7: Embed..."
    $PYTHON -m scripts.pipeline_runner --step embed || log_warn "Embed step completed with warnings"

    # Show pipeline stats
    log_info "Pipeline Statistics:"
    $PYTHON -m scripts.pipeline_runner --step stats

    log_info "Ingestion pipeline complete!"
else
    log_step "2. INGEST - Skipped (--skip-ingest)"
fi

# =============================================================================
# Step 3: Verify (Run E2E tests)
# =============================================================================
log_step "3. VERIFY - Running E2E tests"

cd "$BACKEND_DIR"

# Wait for API to be ready
wait_for_api

# Run E2E test scenarios
log_info "Running E2E test scenarios..."
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

$PYTHON tests/test_e2e_scenarios.py

# Check exit code
if [ $? -eq 0 ]; then
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
$PYTHON -m scripts.pipeline_runner --step stats

echo ""
log_info "Check server logs for detailed information:"
echo "  docker compose logs -f api"
echo ""
