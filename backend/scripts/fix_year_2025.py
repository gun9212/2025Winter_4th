#!/usr/bin/env python3
"""
Fix all document years to 2025.

Usage:
    python scripts/fix_year_2025.py --dry-run
    python scripts/fix_year_2025.py
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.document import Document

import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

FIXED_YEAR = 2025


async def fix_years(dry_run: bool):
    engine = create_async_engine(str(settings.DATABASE_URL))
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Check current state
        stmt = select(Document.id, Document.year, Document.drive_name)
        result = await session.execute(stmt)
        rows = result.fetchall()

        non_2025_count = sum(1 for row in rows if row[1] != FIXED_YEAR)
        logger.info("Current state", total=len(rows), non_2025=non_2025_count)

        if non_2025_count == 0:
            logger.info("All documents already have year=2025")
            return

        if dry_run:
            for row in rows:
                if row[1] != FIXED_YEAR:
                    logger.info("[DRY RUN] Would update", doc_id=row[0], current_year=row[1], new_year=FIXED_YEAR, name=row[2][:50])
            logger.info("Dry run completed", would_update=non_2025_count)
        else:
            # Update all documents to year=2025
            stmt = update(Document).values(year=FIXED_YEAR)
            await session.execute(stmt)
            await session.commit()
            logger.info("All documents updated to year=2025", updated=non_2025_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix document years to 2025")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without changes")
    args = parser.parse_args()

    asyncio.run(fix_years(args.dry_run))
