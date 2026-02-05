#!/usr/bin/env python3
"""
Rollback script to restore Document drive_ids from a backup JSON file.

Usage:
    python scripts/rollback_drive_ids.py --backup-file backup/drive_id_backup_CHECKPOINT.json
"""

import argparse
import asyncio
import json
import os
import sys

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

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

async def rollback(backup_file: str):
    if not os.path.exists(backup_file):
        logger.error("Backup file not found", path=backup_file)
        return

    msg = f"WARNING: This will overwrite drive_ids with data from {backup_file}. Proceed? [y/N] "
    if input(msg).lower() != 'y':
        print("Aborted.")
        return

    logger.info("Loading backup file...", path=backup_file)
    with open(backup_file, "r") as f:
        backup_data = json.load(f)

    logger.info("Backup loaded", count=len(backup_data))

    engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        updated_count = 0
        
        # Process in batches if needed, but for < 10k docs, loop is fine
        for item in backup_data:
            doc_id = item["id"]
            old_drive_id = item["drive_id"]
            
            stmt = (
                update(Document)
                .where(Document.id == doc_id)
                .values(drive_id=old_drive_id)
            )
            await session.execute(stmt)
            updated_count += 1
            
            if updated_count % 100 == 0:
                print(f"Restored {updated_count} records...", end="\r")

        await session.commit()
        logger.info("Rollback completed successfully", total_restored=updated_count)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rollback Drive IDs")
    parser.add_argument("--backup-file", required=True, help="Path to backup JSON file")
    args = parser.parse_args()
    
    asyncio.run(rollback(args.backup_file))
