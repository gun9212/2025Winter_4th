#!/usr/bin/env python3
"""
Migration script to update Document drive_ids from local paths to authentic Google Drive IDs.

Usage:
    python scripts/migrate_drive_ids.py --dry-run
    python scripts/migrate_drive_ids.py

Features:
- Auto-backup of current DB state before changes
- Fetches real Drive IDs using rclone lsjson
- Updates database records
- Preserves drive_path (crucial for file operations)
"""

import argparse
import asyncio
import json
import os
import sys
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.document import Document

# Setup logging
import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

BACKUP_DIR = Path("/tmp/council-ai/backup")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def normalize_filename(filename: str) -> str:
    return unicodedata.normalize("NFC", filename)

async def fetch_drive_map(folder_id: str) -> dict[str, str]:
    """Fetch path -> ID map using rclone lsjson."""
    logger.info("Fetching Drive metadata...", folder_id=folder_id)
    cmd = [
        "rclone", "lsjson", "gdrive:",
        "--drive-root-folder-id", folder_id,
        "--recursive", "--files-only",
        "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        "--drive-skip-shortcuts",
    ]
    
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, check=True
        )
        items = json.loads(result.stdout)
        
        drive_map = {}
        for item in items:
            path = normalize_filename(item["Path"])
            drive_id = item["ID"]
            name = item["Name"]
            
            drive_map[path] = drive_id
            
            # Handle Google Doc exports
            ext = os.path.splitext(name)[1].lower()
            if ext == ".gdoc":
                drive_map[path.replace(".gdoc", ".docx")] = drive_id
            elif ext == ".gsheet":
                drive_map[path.replace(".gsheet", ".xlsx")] = drive_id
            elif ext == ".gslides":
                drive_map[path.replace(".gslides", ".pptx")] = drive_id
                
        return drive_map
    except Exception as e:
        logger.error("Failed to fetch Drive map", error=str(e))
        return {}

async def backup_db(session: AsyncSession) -> str:
    """Backup current drive_ids to JSON file."""
    stmt = select(Document.id, Document.drive_id)
    result = await session.execute(stmt)
    rows = [{"id": row[0], "drive_id": row[1]} for row in result.fetchall()]
    
    filename = BACKUP_DIR / f"drive_id_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(rows, f, indent=2)
    
    logger.info("Database backed up", filename=str(filename), count=len(rows))
    return str(filename)

async def migrate(dry_run: bool):
    engine = create_async_engine(str(settings.DATABASE_URL))
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # 1. Backup
        if not dry_run:
            await backup_db(session)

        # 2. Get documents and extract unique folder IDs from DB paths
        stmt = select(Document).where(Document.drive_id.like("local:%"))
        result = await session.execute(stmt)
        documents = result.scalars().all()

        if not documents:
            logger.info("No documents with local: prefix found")
            return

        # Extract unique folder IDs from DB paths
        # Format: local:FOLDER_ID/path/to/file
        folder_ids = set()
        for doc in documents:
            path = doc.drive_id.replace("local:", "")
            parts = path.split('/', 1)
            if len(parts) > 1 and len(parts[0]) > 20:  # Drive IDs are typically 33+ chars
                folder_ids.add(parts[0])

        logger.info("Found folder IDs in DB", folder_ids=list(folder_ids))

        # 3. Fetch Drive maps for each folder
        combined_drive_map = {}
        for folder_id in folder_ids:
            logger.info("Fetching Drive map for folder", folder_id=folder_id)
            folder_map = await fetch_drive_map(folder_id)
            # Prefix paths with folder_id for matching
            for path, drive_id in folder_map.items():
                combined_drive_map[f"{folder_id}/{path}"] = drive_id
            logger.info("Fetched files from folder", folder_id=folder_id, count=len(folder_map))

        if not combined_drive_map:
            logger.error("Empty Drive map, aborting")
            return

        # 4. Update DB
        updated_count = 0
        skipped_count = 0

        logger.info("Starting migration", total_docs=len(documents), dry_run=dry_run)

        for doc in documents:
            # Extract relative path from local:path
            # drive_id format: local:FOLDER_ID/path/to/file.pdf
            current_path = doc.drive_id.replace("local:", "")
            current_path = normalize_filename(current_path)

            new_id = combined_drive_map.get(current_path)

            if new_id:
                if dry_run:
                    logger.info("[DRY RUN] Would update", doc_id=doc.id, old=doc.drive_id, new=new_id)
                else:
                    doc.drive_id = new_id
                    # IMPORTANT: Do NOT change drive_path
                updated_count += 1
            else:
                logger.warning("No match found for document", doc_id=doc.id, path=current_path)
                skipped_count += 1

        if not dry_run:
            await session.commit()
            logger.info("Migration committed", updated=updated_count, skipped=skipped_count)
        else:
            logger.info("Dry run completed", would_update=updated_count, skipped=skipped_count)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Drive IDs")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without changes")
    args = parser.parse_args()
    
    asyncio.run(migrate(args.dry_run))
