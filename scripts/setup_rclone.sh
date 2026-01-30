#!/bin/bash
# ============================================================================
# setup_rclone.sh - Configure rclone with Google Service Account
# ============================================================================

set -e

# Configuration
REMOTE_NAME="${RCLONE_REMOTE:-gdrive}"
SA_KEY_PATH="${GOOGLE_APPLICATION_CREDENTIALS:-/app/credentials/google_key.json}"
RCLONE_CONFIG_DIR="${HOME}/.config/rclone"
RCLONE_CONFIG_FILE="${RCLONE_CONFIG_DIR}/rclone.conf"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  rclone Setup with Service Account${NC}"
echo -e "${GREEN}============================================${NC}"

# Check if rclone is installed
if ! command -v rclone &> /dev/null; then
    echo -e "${YELLOW}Installing rclone...${NC}"
    curl https://rclone.org/install.sh | sudo bash
fi

# Check if service account key exists
if [ ! -f "${SA_KEY_PATH}" ]; then
    echo -e "${RED}Error: Service account key not found at ${SA_KEY_PATH}${NC}"
    exit 1
fi

echo -e "${GREEN}Service account key found: ${SA_KEY_PATH}${NC}"

# Create rclone config directory
mkdir -p "${RCLONE_CONFIG_DIR}"

# Generate rclone config
cat > "${RCLONE_CONFIG_FILE}" << EOF
[${REMOTE_NAME}]
type = drive
scope = drive
service_account_file = ${SA_KEY_PATH}
team_drive =
EOF

echo -e "${GREEN}rclone configuration created at: ${RCLONE_CONFIG_FILE}${NC}"

# Verify configuration
echo -e "${YELLOW}Verifying rclone configuration...${NC}"
if rclone lsd "${REMOTE_NAME}:" --max-depth 1 2>/dev/null; then
    echo -e "${GREEN}Configuration verified successfully!${NC}"
else
    echo -e "${RED}Warning: Could not list drive contents.${NC}"
    echo -e "${YELLOW}This might be because:${NC}"
    echo -e "  1. Service Account doesn't have access to any shared folders"
    echo -e "  2. You need to share the target folder with the Service Account email"
    echo ""
    echo -e "${YELLOW}Service Account email can be found in: ${SA_KEY_PATH}${NC}"
    echo -e "Share your Google Drive folder with this email address."
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Next steps:"
echo -e "  1. Share your Google Drive folder with the Service Account email"
echo -e "  2. Set GOOGLE_DRIVE_FOLDER_ID environment variable"
echo -e "  3. Run: ./scripts/sync_drive.sh"
