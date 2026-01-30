#!/bin/bash
# ============================================================================
# sync_drive.sh - Google Drive to Local Sync Script using rclone
# ============================================================================

set -e

# Configuration
REMOTE_NAME="${RCLONE_REMOTE:-gdrive}"
FOLDER_ID="${GOOGLE_DRIVE_FOLDER_ID:-}"
LOCAL_PATH="${SYNC_LOCAL_PATH:-/app/data/raw}"
LOG_FILE="${SYNC_LOG_FILE:-/app/logs/sync.log}"

# Export formats for Google Workspace files
# Google Docs -> docx, Google Sheets -> xlsx, Google Slides -> pptx
EXPORT_FORMATS="docx,xlsx,pptx,pdf"

# Whitelist: Only allow these file extensions
# Google Workspace files are exported as: .docx, .xlsx, .pptx
# Native files: .pdf, .hwp, .hwpx, .txt, .csv, .jpg, .png
INCLUDE_PATTERNS=(
    "*.docx"
    "*.xlsx"
    "*.pptx"
    "*.pdf"
    "*.hwp"
    "*.hwpx"
    "*.txt"
    "*.csv"
    "*.jpg"
    "*.jpeg"
    "*.png"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "${LOG_FILE}"
}

# Check prerequisites
check_prerequisites() {
    if ! command -v rclone &> /dev/null; then
        log "ERROR" "${RED}rclone is not installed. Please install it first.${NC}"
        exit 1
    fi

    if [ -z "${FOLDER_ID}" ]; then
        log "ERROR" "${RED}GOOGLE_DRIVE_FOLDER_ID is not set.${NC}"
        exit 1
    fi

    # Create directories if not exist
    mkdir -p "${LOCAL_PATH}"
    mkdir -p "$(dirname "${LOG_FILE}")"
}

# Build include arguments (whitelist approach)
build_include_args() {
    local include_args=""
    for pattern in "${INCLUDE_PATTERNS[@]}"; do
        include_args="${include_args} --include ${pattern}"
    done
    # Exclude everything else
    include_args="${include_args} --exclude *"
    echo "${include_args}"
}

# Main sync function
sync_drive() {
    log "INFO" "${GREEN}Starting Google Drive sync...${NC}"
    log "INFO" "Remote: ${REMOTE_NAME}"
    log "INFO" "Folder ID: ${FOLDER_ID}"
    log "INFO" "Local Path: ${LOCAL_PATH}"
    log "INFO" "Allowed extensions: ${INCLUDE_PATTERNS[*]}"

    local include_args=$(build_include_args)

    # Run rclone copy with whitelist filtering
    # Using --drive-root-folder-id to specify the folder
    rclone copy "${REMOTE_NAME}:/" "${LOCAL_PATH}" \
        --drive-root-folder-id "${FOLDER_ID}" \
        --drive-export-formats "${EXPORT_FORMATS}" \
        --progress \
        --transfers 10 \
        --checkers 8 \
        --contimeout 60s \
        --timeout 300s \
        --retries 3 \
        --low-level-retries 10 \
        --stats 30s \
        --log-file "${LOG_FILE}" \
        --log-level INFO \
        ${include_args}

    local exit_code=$?

    if [ ${exit_code} -eq 0 ]; then
        log "INFO" "${GREEN}Sync completed successfully!${NC}"

        # Count synced files
        local file_count=$(find "${LOCAL_PATH}" -type f | wc -l | tr -d ' ')
        log "INFO" "Total files synced: ${file_count}"
    else
        log "ERROR" "${RED}Sync failed with exit code: ${exit_code}${NC}"
        exit ${exit_code}
    fi
}

# Cleanup old logs (keep last 7 days)
cleanup_logs() {
    if [ -d "$(dirname "${LOG_FILE}")" ]; then
        find "$(dirname "${LOG_FILE}")" -name "*.log" -mtime +7 -delete 2>/dev/null || true
    fi
}

# Main execution
main() {
    log "INFO" "============================================"
    log "INFO" "Google Drive Sync Script Started"
    log "INFO" "============================================"

    check_prerequisites
    cleanup_logs
    sync_drive

    log "INFO" "============================================"
    log "INFO" "Script finished"
    log "INFO" "============================================"
}

# Run main function
main "$@"
